from google import genai
import sys

api_key = input("APIキーを入力してください: ").strip()
client = genai.Client(api_key=api_key)

print("\n利用可能なモデル一覧:")
for m in client.models.list():
    if "generateContent" in (m.supported_actions or []):
        print(f"  {m.name}")
