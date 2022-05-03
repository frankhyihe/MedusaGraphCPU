import argparse
import numpy as np
import os
import sys

import torch
import torch.nn.functional as F
from torch_geometric.data import DataLoader
from torch_geometric.nn import GATConv, global_mean_pool
from torch_geometric.data import DataLoader

from dataset import PDBBindCoor, PDBBindNextStep2
from model import Net_coor, Net_screen
from molecular_optimization import get_refined_pose_file


parser = argparse.ArgumentParser()
parser.add_argument("--gpu_id", help="id of gpu", type=int, default = 0)
parser.add_argument("--ligand_file", help="input ligand file", type=str, default = None)
parser.add_argument("--protein_file", help="input protein file", type=str, default = None)
parser.add_argument("--pose_file", help="input pose file generated by MedusaDock", type=str, default = None)
parser.add_argument("--output_file", help="output file of the ligand", type=str, default = None)
parser.add_argument("--prediction_model", help="direct to the pre-trained pose prediction model", type=str, default = None)
parser.add_argument("--selection_model", help="direct to the pre-trained pose selection model", type=str, default = None)
parser.add_argument("--tmp_dir", help="tmp dir for processing the MedusaGraph", type=str, default = None)
args = parser.parse_args()
print(args)


def convert_data(input_list, output_file, groundtruth_dir, pdbbind_dir, label_list_file):
	cmd_str = f'python convert_data_to_disk.py --input_list={input_list} --output_file={output_file} --thread_num=1 '
	cmd_str = cmd_str + f'--use_new_data --bond_th=6 --pocket_th=12 --groundtruth_dir={groundtruth_dir} '
	cmd_str = cmd_str + f'--pdbbind_dir={pdbbind_dir} --label_list_file={label_list_file} --dataset=coor2 --pdb_version=2016'

	os.system(cmd_str)
	data_dir = os.path.join(label_list_file, output_file)
	data_raw_dir = os.path.join(data_dir, 'raw')
	os.system(f'mkdir {data_raw_dir}')
	os.system(f'mv {data_dir}/test {data_raw_dir}')
	os.system(f'mv {data_dir}/train {data_raw_dir}')

	return data_dir


def generate_pose(data_dir, prediction_model, device):
	test_dataset=PDBBindCoor(root=data_dir, split='test', data_type='autodock')
	test_loader=DataLoader(test_dataset, batch_size=1)
	model = torch.load(prediction_model).to(device)

	output_poses = []
	for data in test_loader:
		out = model(data.x.to(device), data.edge_index.to(device), data.dist.to(device))[data.flexible_idx.bool()]
		output_poses.append((data.x[data.flexible_idx.bool(), -3:] + out.detach().cpu()).numpy()*100)

	return output_poses


def select_pose(data_dir, prediction_model, selection_model, output_poses, ligand_file, output_file, device):
	data_dir_2 = data_dir + '_2'

	test_dataset = PDBBindNextStep2(root=data_dir_2, model_dir=prediction_model, gpu_id=0, pre_root=data_dir, split='test')
	train_dataset = PDBBindNextStep2(root=data_dir_2, model_dir=prediction_model, gpu_id=0, pre_root=data_dir, split='train')
	test_dataset=PDBBindCoor(root=data_dir_2, split='test')
	test_loader=DataLoader(test_dataset, batch_size=1)
	model = torch.load(selection_model).to(device)

	score = []
	for data in test_loader:
		data = data.to(device)
		out = model(data.x, data.edge_index, data.dist, data.flexible_idx.bool(), data.batch)
		out = out.detach().cpu().numpy()[0, 1]
		score.append(out)

	max_idx = 0
	max_score = score[0]
	for idx in range(1, len(score)):
		if score[idx] > max_score:
			max_score = score[idx]
			max_idx = idx

	get_refined_pose_file(ligand_file, output_file, output_poses[max_idx])





# python /gpfs/group/mtk2/cyberstar/hzj5142/GNN/GNN/DGNN/convert_data_to_disk.py --cv=0
# --input_list=/gpfs/group/mtk2/cyberstar/hzj5142/MedusaGraph/data/pdb_list_ --output_file=pdbbind_rmsd_srand_coor2
# --thread_num=1 --use_new_data --bond_th=6 --pocket_th=12
# --groundtruth_dir=/gpfs/group/mtk2/cyberstar/hzj5142/MedusaGraph/data/pdbbind/
# --pdbbind_dir=/gpfs/group/mtk2/cyberstar/hzj5142/MedusaGraph/data/medusadock_output
# --label_list_file=/gpfs/group/mtk2/cyberstar/hzj5142/MedusaGraph_tmp --dataset=coor2 --pdb_version=2016
if __name__ == "__main__":
	ligand_file = args.ligand_file
	protein_file = args.protein_file
	pose_file = args.pose_file
	output_file = args.output_file
	tmp_dir = args.tmp_dir
	prediction_model = args.prediction_model
	selection_model = args.selection_model
	gpu_id = str(args.gpu_id)
	device_str = 'cuda:' + gpu_id if torch.cuda.is_available() else 'cpu'
	device = torch.device(device_str)

	if not os.path.isdir(tmp_dir):
		os.makedirs(tmp_dir)
	pdb_list_train = os.path.join(tmp_dir, 'pdb_list_train')
	pdb_list_test = os.path.join(tmp_dir, 'pdb_list_test')
	input_list = os.path.join(tmp_dir, 'pdb_list_')
	groundtruth_dir = os.path.join(tmp_dir, 'pdbbind/')
	pdbbind_dir = os.path.join(tmp_dir, 'pdbbind/abcd')
	if not os.path.isdir(pdbbind_dir):
		os.system(f'mkdir -p {pdbbind_dir}')
	label_list_file = tmp_dir

	with open(pdb_list_train, 'w') as f:
		f.write('abcd\n')
	with open(pdb_list_test, 'w') as f:
		f.write('abcd\n')

	os.system(f'cp {ligand_file} {pdbbind_dir}/abcd.lig.mol2')
	os.system(f'cp {protein_file} {pdbbind_dir}/abcd.rec.pdb')
	os.system(f'cp {pose_file} {pdbbind_dir}/abcd.pdb')

	data_dir = convert_data(input_list, 'pdbbind_rmsd_srand_coor2', groundtruth_dir, pdbbind_dir, label_list_file)
	output_poses = generate_pose(data_dir, prediction_model, device)
	select_pose(data_dir, prediction_model, selection_model, output_poses, ligand_file, output_file, device)