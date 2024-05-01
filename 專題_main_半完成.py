# -*- coding: utf-8 -*-
"""專題-main-半完成.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1IV6GS_H1CCv48NNuke5EFjY962Dp-ap6
"""

import argparse
import math
import time
import torch
import torch.nn.functional as F
import torch.optim as optim
import logging
from datetime import datetime
import os
from torch.utils.data import Dataset, DataLoader
from os.path import join, exists
from torch.nn import CrossEntropyLoss
from tqdm import tqdm
from torch.nn import DataParallel
import transformers
import pickle
import sys
#from pytorchtools import EarlyStopping
from sklearn.model_selection import train_test_split
#from data_parallel import BalancedDataParallel
from transformers import GPT2TokenizerFast, GPT2LMHeadModel, GPT2Config
from transformers import BertTokenizerFast
import pandas as pd
import torch.nn.utils.rnn as rnn_utils
import numpy as np
#from dataset import MyDataset

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

from torch.nn.parallel import DataParallel
import torch
from torch.nn.parallel._functions import Scatter
from torch.nn.parallel.parallel_apply import parallel_apply


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

def set_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--device', default='3', type=str, required=False, help='设置使用哪些显卡')
    #parser.add_argument('--no_cuda', action='store_true', help='不使用GPU进行训练')
    parser.add_argument('--vocab_path', default='vocab/vocab.txt', type=str, required=False,help='词表路径')
    parser.add_argument('--model_config', default='config/config.json', type=str, required=False,help='设置模型参数')
    parser.add_argument('--train_path', default='data/train.pkl', type=str, required=False, help='训练集路径')
    parser.add_argument('--max_len', default=150, type=int, required=False, help='训练时，输入数据的最大长度')

    #parser.add_argument('--log_path', default='data/train.log', type=str, required=False, help='训练日志存放位置')
    #parser.add_argument('--log', default=True, help="是否记录日志")
    parser.add_argument('--ignore_index', default=-100, type=int, required=False, help='对于ignore_index的label token不计算梯度')
    # parser.add_argument('--input_len', default=200, type=int, required=False, help='输入的长度')
    parser.add_argument('--epochs', default=100, type=int, required=False, help='训练的最大轮次')
    parser.add_argument('--batch_size', default=4, type=int, required=False, help='训练的batch size')
    parser.add_argument('--gpu0_bsz', default=10, type=int, required=False, help='0号卡的batch size')
    parser.add_argument('--lr', default=2.6e-5, type=float, required=False, help='学习率')
    parser.add_argument('--eps', default=1.0e-09, type=float, required=False, help='衰减率')
    parser.add_argument('--log_step', default=1, type=int, required=False, help='多少步汇报一次loss')
    parser.add_argument('--gradient_accumulation_steps', default=4, type=int, required=False, help='梯度积累')
    parser.add_argument('--max_grad_norm', default=2.0, type=float, required=False)
    parser.add_argument('--save_model_path', default='model', type=str, required=False,
                        help='模型输出路径')
    parser.add_argument('--pretrained_model', default='', type=str, required=False,
                        help='预训练的模型的路径')
    # parser.add_argument('--seed', type=int, default=None, help='设置种子用于生成随机数，以使得训练的结果是确定的')
    parser.add_argument('--num_workers', type=int, default=0, help="dataloader加载数据时使用的线程数量")
    #parser.add_argument('--patience', type=int, default=0, help="用于early stopping,设为0时,不进行early stopping.early stop得到的模型的生成效果不一定会更好。")
    parser.add_argument('--warmup_steps', type=int, default=4000, help='warm up步数')
    # parser.add_argument('--label_smoothing', default=True, action='store_true', help='是否进行标签平滑')
    parser.add_argument('--val_num', type=int, default=8000, help='验证集大小')
    args = parser.parse_args()
    return args

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
    with open("tran.pkl", "wb") as f:
        pickle.dump(dialogue_list, f)
    print("finish preprocessing data,the result is stored in {}".format(args.save_path))
    print("mean of dialogue len:{},median of dialogue len:{},max len:{}".format(len_mean, len_median, len_max))

    with open("tran.pkl", "rb") as f:
        input_list = pickle.load(f)

    # 划分训练集与验证集
    val_num = 8000
    input_list_train = input_list[val_num:]
    input_list_val = input_list[:val_num]


    train_dataset = MyDataset(input_list_train, 150)
    val_dataset = MyDataset(input_list_val, 150)

    return train_dataset, val_dataset

cuda = torch.cuda.is_available() and not args.no_cuda
device = 'cuda:0' if cuda else 'cpu'

# 初始化tokenizer
tokenizer = BertTokenizerFast(vocab_file='vocab.txt', sep_token="[SEP]", pad_token="[PAD]", cls_token="[CLS]")
sep_id = tokenizer.sep_token_id
pad_id = tokenizer.pad_token_id
cls_id = tokenizer.cls_token_id

if '':  # 加載預訓練模型
  model = GPT2LMHeadModel.from_pretrained(model_name)
else:  # 初始化模型
  model_config = GPT2Config.from_json_file('config.json')
  model = GPT2LMHeadModel(config=model_config)
model = model.to(device)
print('model config:\n{}'.format(model.config.to_json_string()))
assert model.config.vocab_size == tokenizer.vocab_size

# 并行訓練模型
if cuda and torch.cuda.device_count() > 1:
    model = DataParallel(model).cuda()
    # model = BalancedDataParallel(args.gpu0_bsz, model, dim=0).cuda()
    print("use GPU {} to train".format(device))

model = GPT2LMHeadModel.from_pretrained('')
model = model.to('0')
model.eval()

if 'sample/':
    if not os.path.exists('sample/'):
        os.makedirs('sample/')
    samples_file = open('sample/' + '/samples.txt', 'a', encoding='utf8')
    samples_file.write("聊天记录{}:\n".format(datetime.now()))

history = []
print('开始和chatbot聊天')
while True:
    text = input("user:")
    # text = "你好"
    if 'model':
        samples_file.write("user:{}\n".format(text))
        text_ids = tokenizer.encode(text, add_special_tokens=False)
        history.append(text_ids)
        input_ids = [tokenizer.cls_token_id]  # 每個input以[CLS]為開頭
        for history_id, history_utr in enumerate(history[-3:]):
            input_ids.extend(history_utr)
            input_ids.append(tokenizer.sep_token_id)
        input_ids = torch.tensor(input_ids).long().to('0')
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
        print("chatbot:" + "".join(text))
        if args.save_samples_path:
            samples_file.write("chatbot:{}\n".format("".join(text)))
    if user_input.lower() in ["exit", "quit", "bye"]:
        print("Chatbot: Goodbye!")
        break