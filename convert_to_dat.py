# filename: convert_to_dat.py
import struct
import os

CSV_FILE = 'dataset.csv'
DAT_FILE = 'dataset.dat'

# Define the binary format:
# 'q' = 8-byte signed integer (for the key)
# '100s' = 100-byte string (for the value)
RECORD_FORMAT = 'q100s'
RECORD_SIZE = struct.calcsize(RECORD_FORMAT)

print(f"Converting '{CSV_FILE}' to '{DAT_FILE}'...")
print(f"Record format: {RECORD_FORMAT}, Record size: {RECORD_SIZE} bytes")

if not os.path.exists(CSV_FILE):
    print(f"Error: {CSV_FILE} not found!")
else:
    with open(CSV_FILE, 'r') as csvfile, open(DAT_FILE, 'wb') as datfile:
        next(csvfile) # Skip header
        
        for i, line in enumerate(csvfile):
            try:
                key_str, value_str = line.strip().split(',', 1) # Split only on the first comma
                key = int(key_str)
                
                # Prepare the value: encode to bytes and truncate/pad to 100 bytes
                value_bytes = value_str.encode('utf-8')[:100].ljust(100, b'\x00')
                
                # Pack the key and value into a binary record
                record = struct.pack(RECORD_FORMAT, key, value_bytes)
                datfile.write(record)

                if (i + 1) % 1000000 == 0:
                    print(f"  ...processed {i+1:,} records.")
            
            except (ValueError, IndexError):
                print(f"Skipping malformed line: {line.strip()}")
                
    print("Conversion complete.")