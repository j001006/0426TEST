from fastapi import FastAPI
from pydantic import BaseModel
from mindmap_generator import generate_mindmap

app = FastAPI()

class InputText(BaseModel):
    text: str

@app.post("/mindmap")
def create_mindmap(data: InputText):
    result = generate_mindmap(data.text)
    return result