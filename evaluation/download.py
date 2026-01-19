from openai import OpenAI
from pathlib import Path

client = OpenAI()

batch_id = "batch_696df9826c5881908ca98b30fc257541"
b = client.batches.retrieve(batch_id)

print("status:", b.status)
print("request_counts:", b.request_counts)  # total/completed/failed
print("output_file_id:", b.output_file_id)
print("error_file_id:", b.error_file_id)
print("errors:", b.errors)

out_dir = Path("./out_debug")
out_dir.mkdir(parents=True, exist_ok=True)

b = client.batches.retrieve(batch_id)
if not b.error_file_id:
    raise RuntimeError("No error_file_id found; print b.request_counts and b.errors first.")

resp = client.files.content(b.error_file_id)

# 写到本地：error_file 是 jsonl，每行对应一个 custom_id 的失败信息
path = out_dir / "batch_error.jsonl"
if hasattr(resp, "text") and resp.text is not None:
    path.write_text(resp.text, encoding="utf-8")
else:
    path.write_bytes(getattr(resp, "content", b""))

print("saved:", path)

