export OPENAI_API_KEY="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"

python ./evaluation/eval_proactivity.py \
  --user_data_dir ./user_data \
  --out_dir ./out_proactivity_eval \
  --model gpt-5.2-pro \
  --reasoning_effort high \
  --user_filter user16
