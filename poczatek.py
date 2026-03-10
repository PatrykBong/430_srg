import os
import threading
import pandas as pd
import numpy as np
import uvicorn
import struct
from fastapi import FastAPI
from scapy.all import sniff, Packet, conf

app = FastAPI()

class TestSession:
    def __init__(self):
        self.is_running = False
        self.current_test_id = ""
        self.data_buffer = []

session = TestSession()
#<1> -> cmd.exe <2> -> /c curl "http://localhost:5005/start/1"
def handle_sv_packet(packet: Packet):
    if session.is_running:
        print("otrzymano pakiet") #do testów, nie używać, w przeciwnym razie zakomentuj linijke
        try:
            raw = packet.load
            va = struct.unpack('!i', raw[0:4])[0] #sprawdzić w wiresharku
            vb = struct.unpack('!i', raw[8:12])[0]
            vc = struct.unpack('!i', raw[16:20])[0]
            ia = struct.unpack('!i', raw[32:36])[0]
            ib = struct.unpack('!i', raw[40:44])[0]
            ic = struct.unpack('!i', raw[48:52])[0]
            
            session.data_buffer.append([va, vb, vc, ia, ib, ic])
        except Exception as e:
            pass

def sniffer_worker():
    print("📡 Sniffer: Rozpoczęto nasłuchiwanie na interfejsie...")
    sniff(filter="ether proto 0x88ba", prn=handle_sv_packet, store=0) #z urządzeniem
    #sniff(iface=conf.iface, prn=handle_sv_packet, store=0) #do testów lokalnie

threading.Thread(target=sniffer_worker, daemon=True).start()

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
        data_array = np.array(session.data_buffer)
        df = pd.DataFrame(data_array, columns=['Va', 'Vb', 'Vc', 'Ia', 'Ib', 'Ic'])
        
        folder = f"./wyniki/{session.current_test_id}"
        os.makedirs(folder, exist_ok=True)
        path = f"{folder}/pomiary.csv"
        df.to_csv(path, index=False)

        #plot = create_plot()
        
        session.data_buffer = []
        return {"status": "saved", "path": path, "samples": len(df)}
    
    return {"status": "no_data"}

def create_plot():
    return 0

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=5005)
#py -m uvicorn main:app --reload --port 5005