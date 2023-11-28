#!/bin/bash
#SBATCH --cpus-per-task=4
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=4
#SBATCH -t 1-0:0
#SBATCH -p fvl
#SBATCH --gpus-per-node=4
#SBATCH --mem=256GB
#SBATCH --qos=medium
#SBATCH -o /share/ckpt/wangyaoning/log/output%j.txt
#SBATCH -e /share/ckpt/wangyaoning/log/error%j.txt

python3 projects/IDOL/train_net.py --config-file projects/IDOL/configs/ytvis19_r50.yaml --num-gpus 4
