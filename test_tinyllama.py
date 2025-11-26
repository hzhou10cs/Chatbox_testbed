import torch
from transformers import AutoTokenizer, AutoModelForCausalLM

model_name = "TinyLlama/TinyLlama-1.1B-Chat-v1.0"

print("Loading tokenizer...")
tokenizer = AutoTokenizer.from_pretrained(model_name)

print("Loading model on GPU with fp16...")
model = AutoModelForCausalLM.from_pretrained(
    model_name,
    torch_dtype=torch.float16,   # 关键：用半精度减少显存
    device_map="auto",          # 让 transformers 自动把模型放到 GPU
)

messages = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Say one short sentence about healthy diet."},
]

prompt = tokenizer.apply_chat_template(
    messages, tokenize=False, add_generation_prompt=True
)

inputs = tokenizer(prompt, return_tensors="pt").to(model.device)

with torch.no_grad():
    outputs = model.generate(
        **inputs,
        max_new_tokens=64,   # 限制生成长度，减少 KV 显存
        do_sample=True,
        temperature=0.7,
        top_p=0.9,
    )

text = tokenizer.decode(outputs[0], skip_special_tokens=True)
print("\n=== MODEL OUTPUT ===")
print(text)
