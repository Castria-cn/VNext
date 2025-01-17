# ------------------------------------------------------------------------
# IDOL: In Defense of Online Models for Video Instance Segmentation
# Copyright (c) 2022 ByteDance. All Rights Reserved.
# ------------------------------------------------------------------------


import torch
import torch.nn as nn
import torchvision
from ..util.box_ops import box_cxcywh_to_xyxy, generalized_box_iou
from ..util.ot_logger import OneTimeLogger
import random
import torchvision.ops as ops

logger = OneTimeLogger('ot_log.txt', clear=True)

def get_sword_contrast(object_queue: torch.tensor, sword_pos: torch.tensor, sword_neg: torch.tensor) -> torch.tensor:
    """
    Calculate sword contrastive loss.
    - object_queue: The object queue in SWORD.
    - sword_pos: positive samples(k+) in SWORD, (pos, dim)
    - sword_neg: negative samples(k-) in SWORD, (neg, dim)

    returns: contrastive loss L_{con}.
    """
    object_center = object_queue.object_center().detach()
    logger.log_id(f'center shape: {object_center.shape}, pos & neg shape: {sword_pos.shape}, {sword_neg.shape}', 99)
    pos_product = torch.einsum('d,pd->p', [object_center, sword_pos]) # [pos]
    neg_product = torch.einsum('d,nd->n', [object_center, sword_neg]) # [neg]
    
    all_sum = torch.logsumexp(torch.cat([pos_product, neg_product]), 0)
    pos_sum = torch.logsumexp(torch.cat([pos_product]), 0)

    logger.log_id(f'all_sum = {all_sum}, pos_sum = {pos_sum}', 100)

    return all_sum - pos_sum

def select_pos_neg(ref_box, all_indices, targets, det_targets, embed_head, hs_key, hs_ref, ref_cls, object_queue):

    ref_embeds = embed_head(hs_ref)
    key_embedds = embed_head(hs_key)
    one = torch.tensor(1).to(ref_embeds)
    zero = torch.tensor(0).to(ref_embeds)
    contrast_items = []
    assert len(targets) == len(all_indices)
    # l2_items = []
    for bz_i,(v,detv, indices) in enumerate(zip(targets,det_targets,all_indices)):
        num_insts = len(v["labels"]) 
        # tgt_valid = v["valid"].reshape(num_insts)
        tgt_bbox = v["boxes"].reshape(num_insts,4) 
        tgt_labels = v['labels']
        # tgt_valid = tgt_valid[:,1]    
        ref_box_bz = ref_box[bz_i]
        ref_cls_bz = ref_cls[bz_i]
        logger.log_id(f'ref_box_bz shape={ref_box_bz.shape}', 1)
        logger.log_id(f'ref_cls_bz shape={ref_cls_bz.shape}', 2)
        logger.log_id(f'tgt_bbox shape={tgt_bbox.shape}', 3)
        logger.log_id(f'tgt_labels shape={tgt_labels.shape}', 4)
        tgt_valid = v["valid"]
               
        contrastive_pos = get_pos_idx(ref_box_bz,ref_cls_bz,tgt_bbox,tgt_labels, tgt_valid)
        # pos_idx, neg_idx = contrastive_pos
        # pos_idx = torch.stack(pos_idx)
        # logger.log_id(f'pos_idx = {str(pos_idx)}', 5)
        for inst_i, (valid,matched_query_id) in enumerate(zip(tgt_valid,indices)):
            
            if not valid:  
                continue
            gt_box = tgt_bbox[inst_i].unsqueeze(0)
            key_embed_i = key_embedds[bz_i,matched_query_id].unsqueeze(0)
            # should be the inst_i's positive and negative
            pos_embed = ref_embeds[bz_i][contrastive_pos[0][inst_i]]
            neg_embed = ref_embeds[bz_i][~contrastive_pos[1][inst_i]]

            """
            calculate sword contrastive loss
            """
            sword_pos = ref_embeds[bz_i][contrastive_pos[0][inst_i]]
            sword_neg = ref_embeds[bz_i][contrastive_pos[1][inst_i] & (~contrastive_pos[0][inst_i])]
            sword_contrast = get_sword_contrast(object_queue, sword_pos, sword_neg)


            contrastive_embed = torch.cat([pos_embed,neg_embed],dim=0)
            contrastive_label = torch.cat([one.repeat(len(pos_embed)),zero.repeat(len(neg_embed))],dim=0) 

            contrast = torch.einsum('nc,kc->nk',[contrastive_embed,key_embed_i])

            if len(pos_embed) ==0 :
                num_sample_neg = 10
            elif len(pos_embed)*10 >= len(neg_embed):
                num_sample_neg = len(neg_embed)
            else:
                num_sample_neg = len(pos_embed)*10 

            sample_ids = random.sample(list(range(0, len(neg_embed))), num_sample_neg)

            aux_contrastive_embed = torch.cat([pos_embed,neg_embed[sample_ids]],dim=0)
            aux_contrastive_label = torch.cat([one.repeat(len(pos_embed)),zero.repeat(num_sample_neg)],dim=0) 
            aux_contrastive_embed=nn.functional.normalize(aux_contrastive_embed.float(),dim=1)
            key_embed_i=nn.functional.normalize(key_embed_i.float(),dim=1)    
            cosine = torch.einsum('nc,kc->nk',[aux_contrastive_embed,key_embed_i])

            logger.log_id(f'original contrast: {contrast}', 66)

            contrast_items.append({'contrast':contrast,'label':contrastive_label, 'aux_consin':cosine,'aux_label':aux_contrastive_label,
                                   'sword_contrast': sword_contrast})

    return contrast_items




def get_pos_idx(bz_boxes,bz_out_prob,bz_gtboxs,bz_tgt_ids,valid):
    with torch.no_grad():  
        if False in valid: 
            bz_gtboxs = bz_gtboxs[valid]
            bz_tgt_ids = bz_tgt_ids[valid]

        fg_mask, is_in_boxes_and_center  = \
            get_in_boxes_info(bz_boxes,bz_gtboxs,expanded_strides=32)
        pair_wise_ious = ops.box_iou(box_cxcywh_to_xyxy(bz_boxes), box_cxcywh_to_xyxy(bz_gtboxs))
        # pair_wise_ious_loss = -torch.log(pair_wise_ious + 1e-8)
        
        # Compute the classification cost.
        alpha = 0.25
        gamma = 2.0
        neg_cost_class = (1 - alpha) * (bz_out_prob ** gamma) * (-(1 - bz_out_prob + 1e-8).log())
        pos_cost_class = alpha * ((1 - bz_out_prob) ** gamma) * (-(bz_out_prob + 1e-8).log())
        cost_class = pos_cost_class[:, bz_tgt_ids] - neg_cost_class[:, bz_tgt_ids]
        cost_giou = -generalized_box_iou(box_cxcywh_to_xyxy(bz_boxes),  box_cxcywh_to_xyxy(bz_gtboxs))

        cost = ( cost_class + 3.0 * cost_giou + 100.0 * (~is_in_boxes_and_center) )

        cost[~fg_mask] = cost[~fg_mask] + 10000.0

        
       
        if False in valid:
            indices_batchi_pos = []
            indices_batchi_neg = []
            if valid.sum()>0:
                indices_batchi_pos_s = dynamic_k_matching(cost, pair_wise_ious, int(valid.sum()),10)
                indices_batchi_neg_s = dynamic_k_matching(cost, pair_wise_ious, int(valid.sum()),100)
            valid_idx = 0
            valid_list = valid.tolist()
            for istrue in valid_list:
                if istrue:
                    indices_batchi_pos.append(indices_batchi_pos_s[valid_idx])
                    indices_batchi_neg.append(indices_batchi_neg_s[valid_idx])
                    valid_idx = valid_idx+1
                else:
                    indices_batchi_pos.append(None)
                    indices_batchi_neg.append(None)
            
        else:
            if valid.sum()>0:
                indices_batchi_pos = dynamic_k_matching(cost, pair_wise_ious, bz_gtboxs.shape[0],10)
                indices_batchi_neg = dynamic_k_matching(cost, pair_wise_ious, bz_gtboxs.shape[0],100)
            else:
                indices_batchi_pos = [None]
                indices_batchi_neg = [None]
                # print('empty object in pos_neg select')

    
    return (indices_batchi_pos, indices_batchi_neg)

def get_in_boxes_info(boxes, target_gts, expanded_strides):
    # size (h,w) 
    # size = size[[1,0]].repeat(2) # (w,h,w,h)

    # ori_gt_boxes = target_gts*size
    xy_target_gts = box_cxcywh_to_xyxy(target_gts) #x1y1x2y2
    
    anchor_center_x = boxes[:,0].unsqueeze(1)
    anchor_center_y = boxes[:,1].unsqueeze(1)

    b_l = anchor_center_x > xy_target_gts[:,0].unsqueeze(0)  
    b_r = anchor_center_x < xy_target_gts[:,2].unsqueeze(0) 
    b_t = anchor_center_y > xy_target_gts[:,1].unsqueeze(0)
    b_b = anchor_center_y < xy_target_gts[:,3].unsqueeze(0)
    is_in_boxes = ( (b_l.long()+b_r.long()+b_t.long()+b_b.long())==4)
    is_in_boxes_all = is_in_boxes.sum(1)>0  # [num_query]

    # in fixed center
    center_radius = 2.5
    b_l = anchor_center_x > (target_gts[:,0]-(1*center_radius/expanded_strides)).unsqueeze(0)  
    b_r = anchor_center_x < (target_gts[:,0]+(1*center_radius/expanded_strides)).unsqueeze(0)  
    b_t = anchor_center_y > (target_gts[:,1]-(1*center_radius/expanded_strides)).unsqueeze(0)
    b_b = anchor_center_y < (target_gts[:,1]+(1*center_radius/expanded_strides)).unsqueeze(0)
    is_in_centers = ( (b_l.long()+b_r.long()+b_t.long()+b_b.long())==4)
    is_in_centers_all = is_in_centers.sum(1)>0

    is_in_boxes_anchor = is_in_boxes_all | is_in_centers_all    

    is_in_boxes_and_center = (is_in_boxes & is_in_centers)   

    return is_in_boxes_anchor,is_in_boxes_and_center

def dynamic_k_matching(cost, pair_wise_ious, num_gt, n_candidate_k):
    matching_matrix = torch.zeros_like(cost) 
    ious_in_boxes_matrix = pair_wise_ious
    # n_candidate_k = 10
    
    topk_ious, _ = torch.topk(ious_in_boxes_matrix, n_candidate_k, dim=0)
    dynamic_ks = torch.clamp(topk_ious.sum(0).int(), min=1)
    for gt_idx in range(num_gt):
        _, pos_idx = torch.topk(cost[:,gt_idx], k=dynamic_ks[gt_idx].item(), largest=False)
        matching_matrix[:,gt_idx][pos_idx] = 1.0

    del topk_ious, dynamic_ks, pos_idx

    anchor_matching_gt = matching_matrix.sum(1)
    
    if (anchor_matching_gt > 1).sum() > 0: 
        _, cost_argmin = torch.min(cost[anchor_matching_gt > 1], dim=1) 
        matching_matrix[anchor_matching_gt > 1] *= 0
        matching_matrix[anchor_matching_gt > 1, cost_argmin,] = 1 

    while (matching_matrix.sum(0)==0).any(): 
        num_zero_gt = (matching_matrix.sum(0)==0).sum()
        matched_query_id = matching_matrix.sum(1)>0
        cost[matched_query_id] += 100000.0 
        unmatch_id = torch.nonzero(matching_matrix.sum(0) == 0, as_tuple=False).squeeze(1)
        for gt_idx in unmatch_id:
            pos_idx = torch.argmin(cost[:,gt_idx])
            matching_matrix[:,gt_idx][pos_idx] = 1.0
        if (matching_matrix.sum(1) > 1).sum() > 0: 
            _, cost_argmin = torch.min(cost[anchor_matching_gt > 1], dim=1) 
            matching_matrix[anchor_matching_gt > 1] *= 0 
            matching_matrix[anchor_matching_gt > 1, cost_argmin,] = 1

    assert not (matching_matrix.sum(0)==0).any() 
 
    matched_pos = []
    for gt_idx in range(num_gt):
        matched_pos.append(matching_matrix[:,gt_idx]>0)        

    return matched_pos


