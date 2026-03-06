from scapy.all import Ether, sendp
import struct
import time

# Ustaw swoją kartę sieciową (np. "Ethernet", "Wi-Fi" lub identyfikator z scapy.all.get_if_list())
from scapy.all import conf
INTERFACE = conf.iface
TEST_DURATION = 5  # Czas trwania w sekundach

def send_fake_sv_timed():
    print(f"🚀 Start symulacji CMC 430 (Limit: {TEST_DURATION}s)...")
    
    start_time = time.time()
    packet_count = 0
    
    # Przykładowe dane: Va=230, Vb=-115, Vc=-115, Ia=5, Ib=0, Ic=0 (wartości umowne)
    # iiiiiiiiiiii -> 12 razy 4-bajtowy integer (Wartość, Jakość dla 6 kanałów)
    fake_values = [23000, 0, -11500, 0, -11500, 0, 5000, 0, 0, 0, 0, 0]
    payload = struct.pack('!iiiiiiiiiiii', *fake_values)
    pkt = Ether(dst="01:0c:cd:04:00:00", type=0x88ba) / payload

    while (time.time() - start_time) < TEST_DURATION:
        sendp(pkt, iface=INTERFACE, verbose=False)
        packet_count += 1
        # 0.001s to ok. 1000 pkt/s - wystarczy do testów obciążenia
        time.sleep(0.001) 
    
    end_time = time.time()
    print(f"✅ Symulacja zakończona.")
    print(f"📊 Wysłano pakietów: {packet_count}")
    print(f"⏱ Realny czas: {end_time - start_time:.2f}s")

if __name__ == "__main__":
    try:
        send_fake_sv_timed()
    except PermissionError:
        print("❌ BŁĄD: Uruchom terminal jako ADMINISTRATOR!")
    except Exception as e:
        print(f"❌ Wystąpił błąd: {e}")