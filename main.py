import os
import threading
import pandas as pd
import numpy as np
import uvicorn
import struct
import socket
import threading
from fastapi import FastAPI

app = FastAPI()

class TestSession:
    def __init__(self):
        self.is_running = False
        self.current_test_id = ""
        self.data_buffer = []
        self.num_phasors = 0 # Liczba phasorów
        self.data_offset = 58 # Od tego bajta zaczyna się sekcja Measuurement Data w ramkach
        self.phasor_size = 8 # 8 dla float, 4 dla int, na razie kożystamy z float, w przyszlości można to wyciągnąć z ramki konfiguracyjnej
        self.phasor_names = []
        self.test_list = []

session = TestSession()
#<1> -> cmd.exe <2> -> /c curl "http://localhost:5005/start/1"

# Zamiast filtorwania Sampled Values z całego ruchu Ethernetowego, przechodzę na czytanie socketu; meculpa: "ether proto 0x88ba" to jednak standard dla SV (IEEE 61850) a nie ruch ethernetowy
def c37_worker():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # socket.AF_INET -> IPv4; SOCK_DGRAM -> UDP
    sock.bind(("0.0.0.0", 4712)) # Poet 4712 jest takim półoficjalnym, domyślnym portem dla urządzeń Omicronu
    print(" !!! Server: Oczekiwanie na dane z CMC 430 !!! ")

    while True:
        data, addr = sock.recvfrom(2048)
        
        if data[0] == 0xAA:
            frame_type = data[1] & 0x0F # Wyciągamy typ ramki z młodszych bitów

            # RAMKA KONFIGURACYJNA
            if frame_type in [1, 2, 3]:
                try:
                    # 1. Pobierz liczbę fazorów
                    detected_phasors = struct.unpack('>H', data[82:84])[0]
                    
                    # Aktualizuj nazwy tylko jeśli liczba fazorów się zmieniła lub lista jest pusta
                    if detected_phasors != session.num_phasors or not session.phasor_names:
                        session.num_phasors = detected_phasors
                        session.phasor_names = [] # Czyścimy stare nazwy
                        
                        for i in range(session.num_phasors):
                            # '>16s' -> surowy ciąg znaków
                            raw_name = struct.unpack(f'>16s', data[88 + i*16 : 88 + i*16 + 16])[0]
                            
                            clean_name = raw_name.decode('ascii', errors='ignore').strip()
                            
                            session.phasor_names.append(f"{clean_name}_Val")
                            session.phasor_names.append(f"{clean_name}_Ang")
                        
                        print(f"WYKRYTO: {session.num_phasors} fazorów")
                        
                except Exception as e:
                    print(f"Błąd parsowania konfiguracji: {e}")

            # RAMKA DANYCH
            elif frame_type == 0 and session.is_running:
                # Jeśli jeszcze nie znamy liczby phasorów, pomijamy iterację pentli
                if session.num_phasors == 0:
                    continue 

                try:
                    current_sample = []
                    # Iterujemy po wykrytej liczbie fazorów
                    for i in range(session.num_phasors):
                        start = session.data_offset + (i * session.phasor_size)
                        # Wyciągamy Value i Angle dla każdego phasora
                        val, ang = struct.unpack('>ff', data[start : start + session.phasor_size])
                        current_sample.extend([val, ang])
                    
                    session.data_buffer.append(current_sample)
                except Exception:
                    pass

@app.get("/start/{test_id}")
async def start_test(test_id: str):
    session.current_test_id = test_id
    session.data_buffer = []
    session.is_running = True
    print(f"START: testu {test_id}")
    return {"status": "started", "id": test_id}

@app.get("/stop")
async def stop_test():
    session.is_running = False
    print(f"STOP: Przetwarzanie danych dla testu {session.current_test_id}")

    if session.data_buffer:
        # Można dodać zabezpieczenie jeżeli byłby problem z wczytaniem nazw z session.phasor_names na zasadzie ręcznego nadania im nazw
        df = pd.DataFrame(session.data_buffer, columns=session.phasor_names)
        
        # Dodanie id testu do listy w celu wczytania testów z plików na samym końcu podczas generowannia pdf
        session.test_list.append((session.current_test_id))

        # Zapis do pliku CSV
        folder = f"./wyniki/{session.current_test_id}"
        os.makedirs(folder, exist_ok=True)
        path = f"{folder}/pomiary.csv"
        df.to_csv(path, index=False)
        
        session.data_buffer = []
        return {"status": "saved", "path": path, "samples": len(df)}
    
    return {"status": "no_data"}

@app.get("/finish")
async def finish_tests():
    # End point wywoływany po zakończeniu wszystkich testów
    # W tym miejscu będzie następowało wczytanie danych z plików CSV, przerobienie danych do wykresów i wygenerowanie PDF
    return {"status": "ok"}

def create_plot():
    return 0

if __name__ == "__main__":
    threading.Thread(target=c37_worker, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=5005)
#py -m uvicorn main:app --reload --port 5005