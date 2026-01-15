# python -m vllm.entrypoints.openai.api_server \
#     --model TinyLlama/TinyLlama-1.1B-Chat-v1.0 \
#     --dtype float16 \
#     --max-model-len 2048 \
#     --max-num-seqs 1 \
#     --enforce-eager \
#     --host 0.0.0.0 \
#     --port 8000 

# python app.py
