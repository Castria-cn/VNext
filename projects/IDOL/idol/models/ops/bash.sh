#!/bin/bash
#SBATCH -n 8
#SBATCH -N 1
#SBATCH -t 1-0:0
#SBATCH -p fvl
#SBATCH --qos medium
#SBATCH --gres=gpu:4
#SBATCH --mem=128GB
#SBATCH -o /share/ckpt/wangyaoning/log/output%j.txt
#SBATCH -e /share/ckpt/wangyaoning/log/error%j.txt

python3 test.py
