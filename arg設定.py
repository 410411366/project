# -*- coding: utf-8 -*-
"""arg設定.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1cA811x0UXuTymklL5gIahzdCb3P4mWCf
"""

def set_args():
    #將required設定為False使參數變更為可選參數，而非必須
    parser = argparse.ArgumentParser()
    #3號通常為效能最好的顯示卡
    parser.add_argument('--device', default='3', type=str, required=False, help='設置使用哪些顯卡')
    #parser.add_argument('--no_cuda', action='store_true', help='不使用GPU進行訓練')
    parser.add_argument('--vocab_path', default='vocab/vocab.txt', type=str, required=False,help='詞表路徑')
    parser.add_argument('--model_config', default='config/config.json', type=str, required=False,help='設置模型參數')
    parser.add_argument('--train_path', default='data/train.pkl', type=str, required=False, help='訓練集路徑')
    parser.add_argument('--max_len', default=150, type=int, required=False, help='訓練時，輸入數據的最大長度')

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
    parser.add_argument('--device', default='0', type=str, required=False, help='生成設備')
    #高溫會導致更多隨機性的預測
    parser.add_argument('--temperature', default=1, type=float, required=False, help='生成的temperature')
    parser.add_argument('--topk', default=8, type=int, required=False, help='最高k選1')
    #default預設為0表示不啟用此功能
    parser.add_argument('--topp', default=0, type=float, required=False, help='最高積累概率')
    # parser.add_argument('--model_config', default='config/model_config_dialogue_small.json', type=str, required=False,
    #                     help='模型參數')
    #parser.add_argument('--log_path', default='data/interact.log', type=str, required=False, help='interact日志存放位置')
    parser.add_argument('--vocab_path', default='vocab/vocab.txt', type=str, required=False, help='選擇詞庫')
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

    args = parser.parse_args()
    return args