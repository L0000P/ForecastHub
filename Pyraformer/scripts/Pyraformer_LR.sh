# ETTh1
python long_range_main.py -data ETTh1 -input_size 168 -predict_step 168 -n_head 6
python long_range_main.py -data ETTh1 -input_size 168 -predict_step 336 -n_head 6
python long_range_main.py -data ETTh1 -input_size 336 -predict_step 720 -inner_size 5 -n_head 6

# ETTm1
python long_range_main.py -data ETTm1 -data_path ETTm1.csv -input_size 384 -predict_step 96 \
-window_size [5,5,5] -dropout 0.2 -n_head 6 -d_model 256 -d_bottleneck 64 -d_k 64 -d_v 64;
python long_range_main.py -data ETTm1 -data_path ETTm1.csv -input_size 672 -predict_step 288 \
-window_size [5,5,5] -inner_size 5 -dropout 0.2 -n_head 6 -d_model 256 -d_bottleneck 64 -d_k 64 -d_v 64;
python long_range_main.py -data ETTm1 -data_path ETTm1.csv -input_size 672 -predict_step 672 \
-window_size [6,6,6] -batch_size 16 -dropout 0.2 -n_head 6 -d_model 256 -d_bottleneck 64 -d_k 64 -d_v 64;
