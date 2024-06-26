# -*- coding: utf-8 -*-
"""train+interact未完成版-2.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/12b6h9qBEysNdS1MDAXspRp2xmNfpIWQu
"""

import transformers
import torch
import os
import sys
import json
import random
import pickle
import numpy as np
import argparse
from torch.utils.tensorboard import SummaryWriter
from datetime import datetime
from tqdm import tqdm
from torch.nn import DataParallel
#import logging
from transformers import GPT2TokenizerFast, GPT2LMHeadModel, GPT2Config
from transformers import BertTokenizerFast
from os.path import join, exists
from itertools import zip_longest, chain
#from dataset import MyDataset
from torch.utils.data import Dataset, DataLoader
from torch.nn import CrossEntropyLoss
from sklearn.model_selection import train_test_split
from collections import Counter
import matplotlib.pyplot as plt
from matplotlib.pyplot import MultipleLocator
import torch.nn.functional as F
import math
import time
import pickle
import torch.optim as optim
#from pytorchtools import EarlyStopping
import pandas as pd
import torch.nn.utils.rnn as rnn_utils

from torch.nn.parallel import DataParallel
import torch
from torch.nn.parallel._functions import Scatter
from torch.nn.parallel.parallel_apply import parallel_apply

from torch.utils.data import Dataset
import torch


class MyDataset(Dataset):
    """

    """

    def __init__(self, input_list, max_len):
        self.input_list = input_list
        self.max_len = max_len

    def __getitem__(self, index):
        input_ids = self.input_list[index]
        input_ids = input_ids[:self.max_len]
        input_ids = torch.tensor(input_ids, dtype=torch.long)
        return input_ids

    def __len__(self):
        return len(self.input_list)

def scatter(inputs, target_gpus, chunk_sizes, dim=0):
    r"""
    Slices tensors into approximately equal chunks and
    distributes them across given GPUs. Duplicates
    references to objects that are not tensors.
    """
    def scatter_map(obj):
        if isinstance(obj, torch.Tensor):
            try:
                return Scatter.apply(target_gpus, chunk_sizes, dim, obj)
            except:
                print('obj', obj.size())
                print('dim', dim)
                print('chunk_sizes', chunk_sizes)
                quit()
        if isinstance(obj, tuple) and len(obj) > 0:
            return list(zip(*map(scatter_map, obj)))
        if isinstance(obj, list) and len(obj) > 0:
            return list(map(list, zip(*map(scatter_map, obj))))
        if isinstance(obj, dict) and len(obj) > 0:
            return list(map(type(obj), zip(*map(scatter_map, obj.items()))))
        return [obj for targets in target_gpus]

    # After scatter_map is called, a scatter_map cell will exist. This cell
    # has a reference to the actual function scatter_map, which has references
    # to a closure that has a reference to the scatter_map cell (because the
    # fn is recursive). To avoid this reference cycle, we set the function to
    # None, clearing the cell
    try:
        return scatter_map(inputs)
    finally:
        scatter_map = None


def scatter_kwargs(inputs, kwargs, target_gpus, chunk_sizes, dim=0):
    r"""Scatter with support for kwargs dictionary"""
    inputs = scatter(inputs, target_gpus, chunk_sizes, dim) if inputs else []
    kwargs = scatter(kwargs, target_gpus, chunk_sizes, dim) if kwargs else []
    if len(inputs) < len(kwargs):
        inputs.extend([() for _ in range(len(kwargs) - len(inputs))])
    elif len(kwargs) < len(inputs):
        kwargs.extend([{} for _ in range(len(inputs) - len(kwargs))])
    inputs = tuple(inputs)
    kwargs = tuple(kwargs)
    return inputs, kwargs


class BalancedDataParallel(DataParallel):
    def __init__(self, gpu0_bsz, *args, **kwargs):
        self.gpu0_bsz = gpu0_bsz
        super().__init__(*args, **kwargs)

    def forward(self, *inputs, **kwargs):
        if not self.device_ids:
            return self.module(*inputs, **kwargs)
        if self.gpu0_bsz == 0:
            device_ids = self.device_ids[1:]
        else:
            device_ids = self.device_ids
        inputs, kwargs = self.scatter(inputs, kwargs, device_ids)
        # print('len(inputs)1: ', str(len(inputs)))
        # print('self.device_ids[:len(inputs)]', str(self.device_ids[:len(inputs)]))
        if len(self.device_ids) == 1:
            return self.module(*inputs[0], **kwargs[0])
        replicas = self.replicate(self.module, self.device_ids[:len(inputs)])
        if self.gpu0_bsz == 0:
            replicas = replicas[1:]
        outputs = self.parallel_apply(replicas, device_ids, inputs, kwargs)
        return self.gather(outputs, self.output_device)

    def parallel_apply(self, replicas, device_ids, inputs, kwargs):
        return parallel_apply(replicas, inputs, kwargs, device_ids[:len(inputs)])

    def scatter(self, inputs, kwargs, device_ids):
        bsz = inputs[0].size(self.dim)
        num_dev = len(self.device_ids)
        gpu0_bsz = self.gpu0_bsz
        bsz_unit = (bsz - gpu0_bsz) // (num_dev - 1)
        if gpu0_bsz < bsz_unit:
            chunk_sizes = [gpu0_bsz] + [bsz_unit] * (num_dev - 1)
            delta = bsz - sum(chunk_sizes)
            for i in range(delta):
                chunk_sizes[i + 1] += 1
            if gpu0_bsz == 0:
                chunk_sizes = chunk_sizes[1:]
        else:
            return super().scatter(inputs, kwargs, device_ids)

        # print('bsz: ', bsz)
        # print('num_dev: ', num_dev)
        # print('gpu0_bsz: ', gpu0_bsz)
        # print('bsz_unit: ', bsz_unit)
        # print('chunk_sizes: ', chunk_sizes)
        return scatter_kwargs(inputs, kwargs, device_ids, chunk_sizes, dim=self.dim)

def set_args():
    #將required設定為False使參數變更為可選參數，而非必須
    parser = argparse.ArgumentParser()
    #parser.add_argument('--topk', type=int, default=10, help='Top-K参数')
    #parser.add_argument('--topp', type=float, default=0.8, help='Top-P参数')
    #3號通常為效能最好的顯示卡
    parser.add_argument('--device', default='3', type=str, required=False, help='設置使用哪些顯卡')
    #parser.add_argument('--no_cuda', action='store_true', help='不使用GPU進行訓練')
    #parser.add_argument('--vocab_path', default='vocab/vocab.txt', type=str, required=False,help='詞表路徑')
    #default='config/config.json'
    parser.add_argument('--model_config', default='/config.json', type=str, required=False,help='設置模型參數')
    parser.add_argument('--train_path', default='data/train.pkl', type=str, required=False, help='訓練集路徑')
    #parser.add_argument('--max_len', default=150, type=int, required=False, help='訓練時，輸入數據的最大長度')

    #parser.add_argument('--log_path', default='data/train.log', type=str, required=False, help='訓練日志存放位置')
    #parser.add_argument('--log', default=True, help="是否記錄日志")
    parser.add_argument('--ignore_index', default=-100, type=int, required=False, help='對於ignore_index的label token不計算梯度')
    # parser.add_argument('--input_len', default=200, type=int, required=False, help='輸入的長度')
    #模型較小，輪迴次數不用太多，從100修改為15
    parser.add_argument('--epochs', default=15, type=int, required=False, help='訓練的最大輪次')
    #每次訓練步驟使用的樣本數量由於訓練資料並不多，所以選定為2~4之間
    parser.add_argument('--batch_size', default=4, type=int, required=False, help='訓練的batch size')
    parser.add_argument('--gpu0_bsz', default=10, type=int, required=False, help='0號卡的batch size')
    #將學習率調小 2.6e-5 -> 1e-4 以避免過度訓練期間權重調整過度
    parser.add_argument('--lr', default=1e-4, type=float, required=False, help='學習率')
    parser.add_argument('--eps', default=1.0e-09, type=float, required=False, help='衰減率')
    parser.add_argument('--log_step', default=1, type=int, required=False, help='多少步匯報一次loss')
    #使用2~4之間，避免使用過大量的GPU內存
    parser.add_argument('--gradient_accumulation_steps', default=4, type=int, required=False, help='梯度積累')
    #最大梯度範圍通常設定為1~5之間
    parser.add_argument('--max_grad_norm', default=2.0, type=float, required=False)
    parser.add_argument('--save_model_path', default='model', type=str, required=False,
                        help='模型輸出路徑')
    parser.add_argument('--pretrained_model', default='', type=str, required=False,
                        help='預訓練的模型的路徑')
    # parser.add_argument('--seed', type=int, default=None, help='設置種子用於生成隨機數，以使得訓練的結果是確定的')
    parser.add_argument('--num_workers', type=int, default=0, help="dataloader加載數據時使用的線程數量")
    #parser.add_argument('--patience', type=int, default=0, help="用於early stopping,設為0時,不進行early stopping.early stop得到的模型的生成效果不一定會更好。")
    parser.add_argument('--warmup_steps', type=int, default=4000, help='warm up步數')
    # parser.add_argument('--label_smoothing', default=True, action='store_true', help='是否進行標簽平滑')
    #將訓練集大小設定為資料集的20% 8000 -> 6000
    parser.add_argument('--val_num', type=int, default=6000, help='驗證集大小')

    #使用第一個GPU
    #parser.add_argument('--device', default='0', type=str, required=False, help='生成設備')
    #高溫會導致更多隨機性的預測
    parser.add_argument('--temperature', default=1, type=float, required=False, help='生成的temperature')
    parser.add_argument('--topk', default=8, type=int, required=False, help='最高k選1')
    #default預設為0表示不啟用此功能
    parser.add_argument('--topp', default=0, type=float, required=False, help='最高積累概率')
    # parser.add_argument('--model_config', default='config/model_config_dialogue_small.json', type=str, required=False,
    #                     help='模型參數')
    #parser.add_argument('--log_path', default='data/interact.log', type=str, required=False, help='interact日志存放位置')
    #default='vocab/vocab.txt'
    parser.add_argument('--vocab_path', default='/vocab.txt', type=str, required=False, help='選擇詞庫')
    #
    parser.add_argument('--model_path', default='model/epoch40', type=str, required=False, help='對話模型路徑')
    parser.add_argument('--save_samples_path', default="sample/", type=str, required=False, help="保存聊天記錄的文件路徑")
    parser.add_argument('--repetition_penalty', default=1.0, type=float, required=False,
                        help="重覆懲罰參數，若生成的對話重覆性較高，可適當提高該參數")
    # parser.add_argument('--seed', type=int, default=None, help='設置種子用於生成隨機數，以使得訓練的結果是確定的')
    #發話最大長，超過自動截斷
    parser.add_argument('--max_len', type=int, default=25, help='每個utterance的最大長度,超過指定長度則進行截斷')
    parser.add_argument('--max_history_len', type=int, default=3, help="dialogue history的最大長度")
    #若硬件不支持 GPU 則將其定為TRUE
    parser.add_argument('--no_cuda', action='store_true', help='不使用GPU進行預測')

    args = parser.parse_args(args=[])
    return args


#----------------------------------  pytorchtools  -------------------------------
args=set_args()

class EarlyStopping:
    """Early stops the training if validation loss doesn't improve after a given patience."""
    def __init__(self, patience=7, verbose=False, delta=0, save_path="."):
        """
        Args:
            patience (int): How long to wait after last time validation loss improved.
                            Default: 7
            verbose (bool): If True, prints a message for each validation loss improvement.
                            Default: False
            delta (float): Minimum change in the monitored quantity to qualify as an improvement.
                            Default: 0
        """
        self.patience = patience
        self.verbose = verbose
        self.counter = 0
        self.best_score = None
        self.early_stop = False
        self.val_loss_min = np.Inf
        self.delta = delta
        self.save_path = save_path

    def __call__(self, val_loss, model):

        score = -val_loss

        if self.best_score is None:
            self.best_score = score
            self.save_checkpoint(val_loss, model)
        elif score < self.best_score + self.delta:
            self.counter += 1
            print(f'EarlyStopping counter: {self.counter} out of {self.patience}')
            if self.counter >= self.patience:
                self.early_stop = True
        else:
            self.best_score = score
            self.save_checkpoint(val_loss, model)
            self.counter = 0

    def save_checkpoint(self, val_loss, model):
        '''Saves model when validation loss decrease.'''
        if self.verbose:
            print(f'Validation loss decreased ({self.val_loss_min:.6f} --> {val_loss:.6f}).  Saving model ...')
        # save_path = join(self.save_path, "best_model")
        # if not os.path.exists(save_path):
        #     os.mkdir(save_path)
        # model_to_save = model.module if hasattr(model, 'module') else model
        # model_to_save.save_pretrained(save_path)
        self.val_loss_min = val_loss

#----------------------  generate_dialogue_subset  --------------------------

def generate_subset():
    """
    用于生成训练子集
    :return:
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--raw_data_path', default='data/train.txt', type=str, required=False, help='原始训练语料')
    parser.add_argument('--subset_size', default=1000000, type=int, required=False, help='要获取的对话数据子集的规模')
    parser.add_argument('--subset_data_path', default='data', type=str, required=False,
                        help='数据子集文件路径,指定文件的父目录')
    args = parser.parse_args()
    with open(args.raw_data_path, "r", encoding="utf8") as f:
        data = f.read()
    dialogues = data.split("\n\n")
    subset_size = min(len(dialogues), args.subset_size)

    with open(join(args.subset_data_path, "train_{}w.txt".format(int(subset_size / 10000))), "w", encoding="utf8") as f:
        print("generating subset,please wait a few minutes")
        for dialogue_index, dialogue in enumerate(dialogues):
            if dialogue_index >= subset_size:
                break
            for utterance in dialogue.split("\n"):
                f.writelines(utterance + "\n")
            f.writelines("\n")


def compute_dialogue_length():
    """
    查看聊天语料中的dialogue的长度分布
    :return:
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--raw_data_path', default='data/train.txt', type=str, required=False, help='原始训练语料')
    args = parser.parse_args()
    with open(args.raw_data_path, "r", encoding="utf8") as f:
        data = f.read()
    dialogues = data.split("\n\n")
    # 统计各个dialogue的长度
    dialogues_lengths = [len(dialogue.replace("\n", "")) for dialogue in dialogues]
    counter = Counter(dialogues_lengths)  # {label:sum(label)}
    dialogue_length_arr = list(counter)
    num_arr = [counter[element] for element in list(counter)]
    print(counter[300])

    x_major_locator = MultipleLocator(100)  # MultipleLocator用于设置刻度间隔
    # y_major_locator = MultipleLocator(20000)
    ax = plt.gca()  # ax为两条坐标轴的实例
    ax.xaxis.set_major_locator(x_major_locator)  # 把x轴的主刻度设置为10的倍数
    # ax.yaxis.set_major_locator(y_major_locator)

    plt.xlabel('dialogue length')
    plt.ylabel('number of dialogue')
    # plt.plot(dialogue_length_arr, num_arr, c='green')
    plt.scatter(dialogue_length_arr, num_arr)
    plt.show()
#--------------------- preprocess ------------------------
def preprocess():
  # 初始化tokenizer
    tokenizer = BertTokenizerFast(vocab_file="vocab.txt", sep_token="[SEP]", pad_token="[PAD]", cls_token="[CLS]")
    sep_id = tokenizer.sep_token_id
    cls_id = tokenizer.cls_token_id

    # 读取训练数据集
    with open("train.txt", 'rb') as f:
        data = f.read().decode("utf-8")
    # 开始进行tokenize
    # 保存所有的对话数据,每条数据的格式为："[CLS]utterance1[SEP]utterance2[SEP]utterance3[SEP]"
    dialogue_len = []  # 记录所有对话tokenize之后的长度，用于统计中位数与均值
    dialogue_list = []
    train_data = data.split("\n\n")
    with open("train.pkl", "w", encoding="utf-8") as f:
        for index, dialogue in enumerate(tqdm(train_data)):
            if "\r\n" in data:
                utterances = dialogue.split("\r\n")
            else:
                utterances = dialogue.split("\n")

            input_ids = [cls_id]  # 每个dialogue以[CLS]开头
            for utterance in utterances:
                input_ids += tokenizer.encode(utterance, add_special_tokens=False)
                input_ids.append(sep_id)  # 每个utterance之后添加[SEP]，表示utterance结束
            dialogue_len.append(len(input_ids))
            dialogue_list.append(input_ids)
    len_mean = np.mean(dialogue_len)
    len_median = np.median(dialogue_len)
    len_max = np.max(dialogue_len)
    with open("train.pkl", "wb") as f:
        pickle.dump(dialogue_list, f)
    
    print("mean of dialogue len:{},median of dialogue len:{},max len:{}".format(len_mean, len_median, len_max))

    with open("train.pkl", "rb") as f:
        input_list = pickle.load(f)

    # 划分训练集与验证集
    val_num = 8000
    input_list_train = input_list[val_num:]
    input_list_val = input_list[:val_num]


    train_dataset = MyDataset(input_list_train, 150)
    val_dataset = MyDataset(input_list_val, 150)

    return train_dataset, val_dataset

#----------------------  train  -------------------------

def collate_fn(batch):
    input_ids = rnn_utils.pad_sequence(batch, batch_first=True, padding_value=0)
    labels = rnn_utils.pad_sequence(batch, batch_first=True, padding_value=-100)
    return input_ids, labels

def train_epoch(model, train_dataloader, optimizer, scheduler, epoch, args):
    model.train()
    device = args.device
    ignore_index = args.ignore_index
    epoch_start_time = datetime.now()
    total_loss = 0  # 記錄下整個epoch的loss的總和
    # epoch_correct_num:每個epoch中,output預測正確的word的數量
    # epoch_total_num: 每個epoch中,output預測的word的總數量
    epoch_correct_num, epoch_total_num = 0, 0

    for batch_idx, (input_ids, labels) in enumerate(train_dataloader):
        try:
            input_ids = input_ids.to(device)
            labels = labels.to(device)
            outputs = model.forward(input_ids, labels=labels)
            logits = outputs.logits
            loss = outputs.loss.mean()

            # 統計該batch的預測token的正確數與總數
            batch_correct_num, batch_total_num = calculate_acc(logits, labels, ignore_index=ignore_index)
            # 統計該epoch的預測token的正確數與總數
            epoch_correct_num += batch_correct_num
            epoch_total_num += batch_total_num
            # 計算該batch的accuracy
            batch_acc = batch_correct_num / batch_total_num

            total_loss += loss.item()
            if args.gradient_accumulation_steps > 1:
                loss = loss / args.gradient_accumulation_steps

            loss.backward()
            # 梯度裁剪
            torch.nn.utils.clip_grad_norm_(model.parameters(), args.max_grad_norm)

            # 進行一定step的梯度累計之後，更新參數
            if (batch_idx + 1) % args.gradient_accumulation_steps == 0:
                optimizer.step()
                scheduler.step()
                optimizer.zero_grad()

            if (batch_idx + 1) % args.log_step == 0:
                print(
                    "batch {} of epoch {}, loss {}, batch_acc {}, lr {}".format(
                        batch_idx + 1, epoch + 1, loss.item() * args.gradient_accumulation_steps, batch_acc, scheduler.get_lr()))

            del input_ids, outputs

        except RuntimeError as exception:
            if "out of memory" in str(exception):
                print("WARNING: ran out of memory")
                if hasattr(torch.cuda, 'empty_cache'):
                    torch.cuda.empty_cache()
            else:
                print(str(exception))
                raise exception
    # 記錄當前epoch的平均loss與accuracy
    epoch_mean_loss = total_loss / len(train_dataloader)
    epoch_mean_acc = epoch_correct_num / epoch_total_num
    print(
        "epoch {}: loss {}, predict_acc {}".format(epoch + 1, epoch_mean_loss, epoch_mean_acc))

    print('saving model for epoch {}'.format(epoch + 1))
    model_path = join(args.save_model_path, 'epoch{}'.format(epoch + 1))
    if not os.path.exists(model_path):
        os.mkdir(model_path)
    model_to_save = model.module if hasattr(model, 'module') else model
    model_to_save.save_pretrained(model_path)
    print('epoch {} finished'.format(epoch + 1))
    epoch_finish_time = datetime.now()
    print('time for one epoch: {}'.format(epoch_finish_time - epoch_start_time))

    return epoch_mean_loss

def validate_epoch(model, validate_dataloader, epoch, args):
    logger.info("start validating")
    model.eval()
    device = args.device
    # pad_id = args.pad_id
    # sep_id = args.sep_id
    ignore_index = args.ignore_index
    epoch_start_time = datetime.now()
    total_loss = 0
    # 捕获cuda out of memory exception
    try:
        with torch.no_grad():
            for batch_idx, (input_ids, labels) in enumerate(validate_dataloader):
                input_ids = input_ids.to(device)
                labels = labels.to(device)
                outputs = model.forward(input_ids, labels=labels)
                logits = outputs.logits
                loss = outputs.loss
                loss = loss.mean()

                total_loss += loss.item()
                del input_ids, outputs

            # 记录当前epoch的平均loss
            epoch_mean_loss = total_loss / len(validate_dataloader)
            logger.info(
                "validate epoch {}: loss {}".format(epoch+1, epoch_mean_loss))
            epoch_finish_time = datetime.now()
            logger.info('time for validating one epoch: {}'.format(epoch_finish_time - epoch_start_time))
            return epoch_mean_loss
    except RuntimeError as exception:
        if "out of memory" in str(exception):
            logger.info("WARNING: ran out of memory")
            if hasattr(torch.cuda, 'empty_cache'):
                torch.cuda.empty_cache()
        else:
            logger.info(str(exception))
            raise exception

def train(model, train_dataset, validate_dataset, args):
    train_dataloader = DataLoader(
        train_dataset, batch_size=args.batch_size, shuffle=True, num_workers=args.num_workers, collate_fn=collate_fn,
        drop_last=True
    )
    validate_dataloader = DataLoader(validate_dataset, batch_size=args.batch_size, shuffle=True,
                                     num_workers=args.num_workers, collate_fn=collate_fn, drop_last=True)
    early_stopping = EarlyStopping(args.patience, verbose=True, save_path=args.save_model_path)
    t_total = len(train_dataloader) // args.gradient_accumulation_steps * args.epochs
    optimizer = transformers.AdamW(model.parameters(), lr=args.lr)
    scheduler = transformers.get_linear_schedule_with_warmup(
        optimizer, num_warmup_steps=args.warmup_steps, num_training_steps=t_total
    )

    print('starting training')

    # 用於記錄每個epoch訓練和驗證的loss
    train_losses, validate_losses = [], []
    best_val_loss = float('inf')  # 初始化為正無窮大，這樣，第一次得到的驗證損失值必然會被更新

    for epoch in range(args.epochs):
        # ========== train ========== #
        train_loss = train_epoch(model, train_dataloader, optimizer, scheduler, logger, epoch, args)
        validate_loss = validate_epoch(model, validate_dataloader, logger, epoch, args)

        train_losses.append(train_loss)
        validate_losses.append(validate_loss)

        if validate_loss < best_val_loss:
            best_val_loss = validate_loss
            model_path = os.path.join(args.save_model_path, 'min_ppl_model'.format(epoch + 1))
            os.makedirs(model_path, exist_ok=True)
            model_to_save = model.module if hasattr(model, 'module') else model
            model_to_save.save_pretrained(model_path)

        if args.patience > 0:
            early_stopping(validate_loss, model)
            if early_stopping.early_stop:
                print("Early stopping")
                break

    print('training finished')
    print("train_losses:{}".format(train_losses))
    print("validate_losses:{}".format(validate_losses))

import torch
import torch.nn.functional as F

#使用Reshape更簡潔
def calculate_loss(logit, target, pad_idx, smoothing=True):
    if smoothing:
        logit = logit[..., :-1, :].reshape(-1, logit.size(-1))
        target = target[..., 1:].reshape(-1)

        eps = 0.1
        n_class = logit.size(-1)

        one_hot = torch.zeros_like(logit).scatter(1, target.view(-1, 1), 1)
        one_hot = one_hot * (1 - eps) + (1 - one_hot) * eps / (n_class - 1)
        log_prb = F.log_softmax(logit, dim=1)

        non_pad_mask = target.ne(pad_idx)
        loss = -(one_hot * log_prb).sum(dim=1)
        loss = loss.masked_select(non_pad_mask).mean()
    else:
        logit = logit[..., :-1, :].reshape(-1, logit.size(-1))
        labels = target[..., 1:].reshape(-1)
        loss = F.cross_entropy(logit, labels, ignore_index=pad_idx)
    return loss


def calculate_acc(logit, labels, ignore_index=-100):
    logit = logit[..., :-1, :].reshape(-1, logit.size(-1))
    labels = labels[..., 1:].reshape(-1)

    _, logit = logit.max(dim=-1)
    non_pad_mask = labels.ne(ignore_index)
    n_correct = logit.eq(labels).masked_select(non_pad_mask).sum().item()
    n_word = non_pad_mask.sum().item()
    return n_correct, n_word

#生成文本的過程中,控制生成結果的多樣性和一致性
def top_k_top_p_filtering(logits, top_k=0, top_p=0.0, filter_value=-float('Inf')):
    """ Filter a distribution of logits using top-k and/or nucleus (top-p) filtering
        Args:
            logits: logits distribution shape (vocab size)
            top_k > 0: keep only top k tokens with highest probability (top-k filtering).
            top_p > 0.0: keep the top tokens with cumulative probability >= top_p (nucleus filtering).
                Nucleus filtering is described in Holtzman et al. (http://arxiv.org/abs/1904.09751)
        From: https://gist.github.com/thomwolf/1a5a29f6962089e871b94cbd09daf317
    """
    assert logits.dim() == 1  # batch size 1 for now - could be updated for more but the code would be less clear
    top_k = min(top_k, logits.size(-1))  # Safety check
    if top_k > 0:
        # Remove all tokens with a probability less than the last token of the top-k
        # torch.topk()返回最後一維最大的top_k個元素，返回值為二維(values,indices)
        # ...表示其他維度由計算機自行推斷
        indices_to_remove = logits < torch.topk(logits, top_k)[0][..., -1, None]
        logits[indices_to_remove] = filter_value  # 對於topk之外的其他元素的logits值設為負無窮

    if top_p > 0.0:
        sorted_logits, sorted_indices = torch.sort(logits, descending=True)  # 對logits進行遞減排序
        cumulative_probs = torch.cumsum(F.softmax(sorted_logits, dim=-1), dim=-1)

        # Remove tokens with cumulative probability above the threshold
        sorted_indices_to_remove = cumulative_probs > top_p
        # Shift the indices to the right to keep also the first token above the threshold
        sorted_indices_to_remove[..., 1:] = sorted_indices_to_remove[..., :-1].clone()
        sorted_indices_to_remove[..., 0] = 0

        indices_to_remove = sorted_indices[sorted_indices_to_remove]
        logits[indices_to_remove] = filter_value
    return logits

#-----------------------    interact  -----------------
def main()
preprocess()
args.cuda = torch.cuda.is_available() and not args.no_cuda
device = 'cuda' if args.cuda else 'cpu'
args = set_args()
# 初始化tokenizer
tokenizer = BertTokenizerFast(vocab_file='/vocab.txt', sep_token="[SEP]", pad_token="[PAD]", cls_token="[CLS]")

sep_id = tokenizer.sep_token_id
pad_id = tokenizer.pad_token_id
cls_id = tokenizer.cls_token_id

model_name = "gpt2"

if args.pretrained_model:  # 加载预训练模型
        model = GPT2LMHeadModel.from_pretrained(args.pretrained_model)
else:  # 初始化模型
        model_config = GPT2Config.from_json_file(args.model_config)
        model = GPT2LMHeadModel(config=model_config)
model = model.to(device)
print('model config:\n{}'.format(model.config.to_json_string()))
assert model.config.vocab_size == tokenizer.vocab_size

# 并行訓練模型
#if arg.cuda and torch.cuda.device_count() > 1:
#    model = DataParallel(model).cuda()
#    # model = BalancedDataParallel(args.gpu0_bsz, model, dim=0).cuda()
#    print("use GPU {} to train".format(device))

#原本:model = GPT2LMHeadModel.from_pretrained(args.model_path)
model = GPT2LMHeadModel.from_pretrained(args.model_path)
model = model.to(device)
model.eval()

history = []
print('开始和chatbot聊天')
while True:
    try:
        text = input("user:")
        # text = "你好"
        if 'model':
            text_ids = tokenizer.encode(text, add_special_tokens=False)
            history.append(text_ids)
            input_ids = [tokenizer.cls_token_id]  # 每個input以[CLS]為開頭
            for history_id, history_utr in enumerate(history[-3:]):
                input_ids.extend(history_utr)
                input_ids.append(tokenizer.sep_token_id)
            #原本:input_ids = torch.tensor(input_ids).long().to('0')
            input_ids = torch.tensor(input_ids).long().to(device)
            input_ids = input_ids.unsqueeze(0)
            response = []  # 根據context，生成的response
            # 最多生成max_len个token
            for _ in range(25):
                outputs = model(input_ids=input_ids)
                logits = outputs.logits
                next_token_logits = logits[0, -1, :]
                # 對於已生成的結果generated中的每個token添加一個重複懲罰項，降低其生成概率
                for id in set(response):
                    next_token_logits[id] /= 1.0
                next_token_logits = next_token_logits / 1.0
                # 對於[UNK]的概率設為無窮小，也就是說模型的預測結果不可能是[UNK]這個token
                next_token_logits[tokenizer.convert_tokens_to_ids('[UNK]')] = -float('Inf')
                filtered_logits = top_k_top_p_filtering(next_token_logits, top_k=args.topk, top_p=args.topp)
                # torch.multinomial表示從候選集合中無放回地進行抽取num_samples個元素，權重越高，抽到的幾率越高，返回元素的下標
                next_token = torch.multinomial(F.softmax(filtered_logits, dim=-1), num_samples=1)
                if next_token == tokenizer.sep_token_id:  # 遇到[SEP]則表明response生成結束
                    break
                response.append(next_token.item())
                input_ids = torch.cat((input_ids, next_token.unsqueeze(0)), dim=1)
                # his_text = tokenizer.convert_ids_to_tokens(curr_input_tensor.tolist())
                # print("his_text:{}".format(his_text))
            history.append(response)
            text = tokenizer.convert_ids_to_tokens(response)
            print("chatbot:" ,"{}".format(text))
        if isinstance(text, list):
          text = " ".join(token for token in text if token is not None)  # 将列表转换为字符串并过滤掉None
    except KeyboardInterrupt:
      print("Chatbot: Goodbye!")
      break






if __name__ == '__main__':
    generate_subset()
#    main()

#--------------------   最後備用    -------------------
model_name = "gpt2"
model = GPT2LMHeadModel.from_pretrained(model_name)
tokenizer = GPT2TokenizerFast.from_pretrained(model_name)

# 定義生成回復的函數
def generate_response(prompt, max_length=50, num_return_sequences=1):
    input_ids = tokenizer.encode(prompt, return_tensors="pt")
    output = model.generate(input_ids, max_length=max_length, num_return_sequences=num_return_sequences)
    response = tokenizer.decode(output[0], skip_special_tokens=True)
    return response

# 与聊天机器人互动
while True:
    user_input = input("You: ")
    if user_input.lower() in ["exit", "quit", "bye"]:
        print("Chatbot: Goodbye!")
        break
    response = generate_response(user_input, max_length=50)
    print(f"Chatbot: {response}")
