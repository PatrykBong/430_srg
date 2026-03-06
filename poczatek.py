from fastapi import FastAPI
import os

app = FastAPI()

@app.get("/test/{test_id}")
def test(test_id: str):
    path = f"./wyniki/{test_id}"
    os.makedirs(path, exist_ok=True)
    with open(f"{path}/dane_surowe.csv", "w") as f:
        f.write("Start testu\n")
    
    print(f"Odebrano sygnał z TU! Identyfikator testu: {test_id}")
    return {"status": "ok", "test_id": test_id}