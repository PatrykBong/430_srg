import os
import threading
import pandas as pd
import numpy as np
import uvicorn
import struct
import socket
import threading
from fastapi import FastAPI
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import numpy as np

from config import PORT

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
        self.frame_size = 0
        self.rate_of_transmission = 0
        self.device_id = 0
        self.num_analog_values = 0
        self.analog_values_names = []

session = TestSession()
#<1> -> cmd.exe <2> -> /c curl "http://localhost:5005/start/1"

# Zamiast filtorwania Sampled Values z całego ruchu Ethernetowego, przechodzę na czytanie socketu; meculpa: "ether proto 0x88ba" to jednak standard dla SV (IEEE 61850) a nie ruch ethernetowy
def c37_worker():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # socket.AF_INET -> IPv4; SOCK_DGRAM -> UDP
    sock.bind(("0.0.0.0", PORT or 4713)) # Patrz Wireshark, później przenieść to do init
    print(" !!! Server: Oczekiwanie na dane z CMC 430 !!! ")

    while True:
        data, addr = sock.recvfrom(2048)
        
        if data[0] == 0xAA:
            frame_type = data[1] & 0x0F # Wyciągamy typ ramki z młodszych bitów

            # RAMKA KONFIGURACYJNA
            if frame_type in [1, 2, 3]:
                try:
                    # Pobierz frame size
                    session.frame_size = struct.unpack('>H', data[44:46])[0]
                    # Pobierz id urządzenia
                    session.device_id = struct.unpack('>H', data[46:48])[0]
                    # Pobierz liczbę fazorów
                    detected_phasors = struct.unpack('>H', data[82:84])[0]
                    # Pobierz liczbę analog values
                    session.num_analog_values = struct.unpack('>H', data[84:86])[0]
                    # Pobierz czesctotliwość wysyłania ramek
                    session.rate_of_transmission = struct.unpack('>H', data[session.frame_size-4:session.frame_size-2])[0]
                    
                    
                    # Aktualizuj nazwy tylko jeśli liczba fazorów się zmieniła lub lista jest pusta
                    if detected_phasors != session.num_phasors or not session.phasor_names:
                        session.num_phasors = detected_phasors
                        session.phasor_names = [] # Czyścimy stare nazwy

                        base_offset = 88
                        
                        for i in range(session.num_phasors):
                            # '>16s' -> surowy ciąg znaków
                            p_offset = base_offset + (i * 16)
                            raw_name = struct.unpack(f'>16s', data[p_offset : p_offset + 16])[0]
                            clean_name = raw_name.decode('ascii', errors='ignore').strip()
                            
                            session.phasor_names.append(f"{clean_name}_Val")
                            session.phasor_names.append(f"{clean_name}_Ang")

                        analog_start_offset = base_offset + session.num_phasors*16
                        session.analog_values_names = []

                        for i in range(session.num_analog_values):
                            av_offset = analog_start_offset + (i * 16)
                            raw_name = struct.unpack(f'>16s', data[av_offset : av_offset + 16])[0]
                            clean_name = raw_name.decode('ascii', errors='ignore').strip()
                            session.analog_values_names.append(clean_name)
                        
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
    if not session.test_list:
        print("ERROR: !!! Brak testów do analizy !!!")
        return {"status": "error", "message": "Brak testów"}

    pdf_path = "./wyniki/RAPORT_POMIAROWY.pdf"
    os.makedirs("./wyniki", exist_ok=True)
    
    print(f"Generowanie raportu PDF")
    
    with PdfPages(pdf_path) as pdf:
        # --- KOLEJNE STRONY: WYKRESY (PIONOWO A4) ---
# --- KOLEJNE STRONY: WYKRESY (PIONOWO A4, CZAS BIEGNIE W DÓŁ) ---
        for test_id in session.test_list:
            csv_path = f"./wyniki/{test_id}/pomiary.csv"
            if os.path.exists(csv_path):
                df = pd.read_csv(csv_path)
                
                # 1. Układ: 1 wiersz, 2 kolumny (wykresy obok siebie)
                fig, (ax_u, ax_i) = plt.subplots(1, 2, figsize=(8.27, 11.69))
                fig.suptitle(f"Test ID: {test_id}", fontsize=14, fontweight='bold')

                # 2. Obliczamy oś czasu
                if session.rate_of_transmission > 0:
                    time_axis = [i / session.rate_of_transmission for i in range(len(df))]
                else:
                    time_axis = range(len(df))

                # 3. Wykres Napięć (PO LEWEJ)
                u_cols = [c for c in df.columns if c.startswith('U') and "_Val" in c]
                for col in u_cols:
                    # ZAMIANA: Wartości na X, Czas na Y
                    ax_u.plot(df[col], time_axis, label=col.replace("_Val", ""), linewidth=1.5)
                
                ax_u.set_title("Napięcia [V]")
                ax_u.set_xlabel("U [V]")
                ax_u.set_ylabel("")
                ax_u.invert_xaxis()  # Odwracamy oś Y, żeby czas 0 był na górze strony
                ax_u.yaxis.set_label_position("right")
                ax_u.yaxis.tick_right()
                ax_u.tick_params(axis='y', left=False, right=False, labelleft=False, labelright=False)
                ax_u.grid(True, linestyle='--', alpha=0.3)
                ax_u.legend(loc='lower left', fontsize='7')

                # 4. Wykres Prądów (PO PRAWEJ)
                i_cols = [c for c in df.columns if c.startswith('I') and "_Val" in c]
                for col in i_cols:
                    # ZAMIANA: Wartości na X, Czas na Y
                    ax_i.plot(df[col], time_axis, label=col.replace("_Val", ""), linewidth=1.5)
                
                ax_i.set_title("Prądy [A]")
                ax_i.set_xlabel("I [A]")
                ax_i.set_ylabel("")
                ax_i.invert_xaxis()
                ax_i.yaxis.set_label_position("right")
                ax_i.yaxis.tick_right()
                ax_i.tick_params(axis='y', labelrotation=90)
                ax_i.grid(True, linestyle='--', alpha=0.3)
                ax_i.legend(loc='lower left', fontsize='7')

                # 5. Dopasowanie i zapis
                plt.tight_layout(rect=[0, 0.03, 1, 0.95])
                pdf.savefig(fig)
                plt.close(fig)
                print(f"Dodano test {test_id} (układ pionowy czasowy)")

        summary = plt.figure(figsize=(8.27, 11.69))  # A4 w calach
        plt.axis("off")

        text = f"""
        Frame size = {session.frame_size}
        Device ID = {session.device_id}
        Ilość Analog values = {session.num_analog_values}
        Nazwy Analog Values = {session.analog_values_names}
        Rate of Transmission = {session.rate_of_transmission}
        """

        plt.text(0.1, 0.9, text, fontsize=12, va="top", family="monospace")
        
        pdf.savefig(summary)
        plt.close()

    return {"status": "success", "pdf_path": pdf_path, "tests": session.test_list}
    #return {"status": "ok"}

def create_plot():
    return 0

# DO TESTÓW RYSOWANIA WYKRESÓW
@app.get("/fill")
async def fill_mock_data():
    mock_names = ["UL1", "UL2", "UL3", "U_SEC+", "IL1", "IL2", "IL3", "ISEQ+"]
    session.phasor_names = []
    for name in mock_names:
        session.phasor_names.append(f"{name}_Val")
        session.phasor_names.append(f"{name}_Ang")
    
    session.num_phasors = len(mock_names)
    session.test_list = []
    session.device_id = 1001
    session.frame_size = 341
    session.num_analog_values = 5
    session.analog_values_names = ["name1","name2","name3","different_name1","new_name1"]
    session.rate_of_transmission = 10

    for i in range(1, 6):
        test_id = f"TEST_SYM_{i}"
        session.test_list.append(test_id)
        
        # Tworzymy folder
        folder = f"./wyniki/{test_id}"
        os.makedirs(folder, exist_ok=True)
        
        # Generujemy losowe dane (100 próbek)
        samples = 100
        data = []
        for s in range(samples):
            row = []
            for p in range(session.num_phasors):
                if "U" in mock_names[p]:
                    val = 230 + np.random.uniform(-5, 5)
                else:
                    val = 5 + np.random.uniform(-0.5, 0.5)
                
                ang = (s * 10 + p * 120) % 360 # Symulacja wirującego kąta
                row.extend([val, ang])
            data.append(row)
        
        # Zapisujemy CSV
        df = pd.DataFrame(data, columns=session.phasor_names)
        df.to_csv(f"{folder}/pomiary.csv", index=False)
        
    return {
        "status": "mock_data_created", 
        "tests": session.test_list, 
        "phasors": session.phasor_names
    }

if __name__ == "__main__":
    threading.Thread(target=c37_worker, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=5005)
#py -m uvicorn main:app --reload --port 5005