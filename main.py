import pickle
import os
import bisect
import struct
import time

# ==============================================================================
# CONFIGURATION
# ==============================================================================
PAGE_SIZE = 4096  # Size of a disk page in bytes
ORDER = 100 # Fanout. A larger order means a shorter tree. (PAGE_SIZE // 16) is a good starting point.
INDEX_FILE = 'bplus_tree.idx'
DATASET_FILE = 'dataset.dat' # Make sure this file is in the same directory


# ==============================================================================
# NODE STRUCTURES
# ==============================================================================
class Node:
    def __init__(self, order, is_leaf=False):
        self.order = order
        self.is_leaf = is_leaf
        self.keys = []
        self.parent_page_id = None
        self.page_id = None

    def is_full(self):
        return len(self.keys) >= self.order - 1

class InternalNode(Node):
    def __init__(self, order, is_leaf=False):
        super().__init__(order, is_leaf=False)
        self.children = [] # List of page_ids

class LeafNode(Node):
    def __init__(self, order, is_leaf=False):
        super().__init__(order, is_leaf=True)
        self.values = []
        self.next_leaf_page_id = None # Pointer to the right sibling


# ==============================================================================
# B+ TREE IMPLEMENTATION
# ==============================================================================
class BPlusTree:
    def __init__(self, index_file_path, order):
        self.index_file_path = index_file_path
        self.order = order
        self.cache = {} # Add this cache dictionary
        self.cache_size = 500 
        if os.path.exists(self.index_file_path):
            os.remove(self.index_file_path)
        self.file_handle = open(self.index_file_path, 'wb+')
        self.next_page_id = 0
        self.root_page_id = None

    def _get_new_page_id(self):
        page_id = self.next_page_id
        self.next_page_id += 1
        return page_id

    def _write_node(self, node):
        if node.page_id is None:
            node.page_id = self._get_new_page_id()
            
        # Update the cache with the modified node
        self.cache[node.page_id] = node
        
        # Write the node to disk
        self.file_handle.seek(node.page_id * PAGE_SIZE)
        padded_node = pickle.dumps(node).ljust(PAGE_SIZE, b'\0')
        self.file_handle.write(padded_node)

    def _read_node(self, page_id):
        if page_id is None: return None
        
        # 1. Check the cache first!
        if page_id in self.cache:
            return self.cache[page_id]

        # 2. If not in cache, read from disk
        self.file_handle.seek(page_id * PAGE_SIZE)
        serialized_node = self.file_handle.read(PAGE_SIZE)
        if not serialized_node: return None
        node = pickle.loads(serialized_node.rstrip(b'\0'))

        # 3. Add the new node to the cache
        if len(self.cache) >= self.cache_size:
            # Simple eviction: remove the oldest item
            del self.cache[next(iter(self.cache))] 
        self.cache[page_id] = node
        
        return node
    
    def close(self):
        if self.file_handle:
            self.file_handle.close()
            self.file_handle = None

    def _find_leaf(self, key):
        node_id = self.root_page_id
        while True:
            node = self._read_node(node_id)
            if node.is_leaf:
                return node
            child_idx = bisect.bisect_right(node.keys, key)
            node_id = node.children[child_idx]

    def insert(self, key, value):
        if self.root_page_id is None:
            root = LeafNode(order=self.order)
            root.page_id = self._get_new_page_id()
            self.root_page_id = root.page_id
            root.keys.append(key)
            root.values.append(value)
            self._write_node(root)
            return

        leaf = self._find_leaf(key)
        pos = bisect.bisect_left(leaf.keys, key)
        leaf.keys.insert(pos, key)
        leaf.values.insert(pos, value)

        if leaf.is_full():
            self._split_leaf(leaf)
        else:
            self._write_node(leaf)

    def _split_leaf(self, leaf):
        new_leaf = LeafNode(order=self.order)
        new_leaf.parent_page_id = leaf.parent_page_id
        mid_index = self.order // 2
        
        new_leaf.keys = leaf.keys[mid_index:]
        new_leaf.values = leaf.values[mid_index:]
        leaf.keys = leaf.keys[:mid_index]
        leaf.values = leaf.values[:mid_index]
        
        self._write_node(new_leaf)
        new_leaf.next_leaf_page_id = leaf.next_leaf_page_id
        leaf.next_leaf_page_id = new_leaf.page_id
        
        self._write_node(leaf)
        self._write_node(new_leaf)
        
        promoted_key = new_leaf.keys[0]
        self._insert_in_parent(leaf, promoted_key, new_leaf)

    def _insert_in_parent(self, old_node, key, new_node):
       # Case 1: The node that split was the root.
        if self.root_page_id == old_node.page_id:
            # We need to create a new root.
            new_root = InternalNode(order=self.order)
            new_root.keys = [key]
            new_root.children = [old_node.page_id, new_node.page_id]
            
            # Write the new root and update the tree's root pointer.
            self._write_node(new_root)
            self.root_page_id = new_root.page_id
            
            # Update the parent pointers of the two children.
            old_node.parent_page_id = new_root.page_id
            new_node.parent_page_id = new_root.page_id
            self._write_node(old_node)
            self._write_node(new_node)
            return

        # Case 2: The parent is not the root.
        parent = self._read_node(old_node.parent_page_id)
        
        # Find where to insert the new key and child pointer in the parent
        child_idx = bisect.bisect_right(parent.keys, key)
        parent.keys.insert(child_idx, key)
        parent.children.insert(child_idx + 1, new_node.page_id)

        # Check if the parent is now full.
        if parent.is_full():
            # If the parent is full, you must split it.
            self._split_internal_node(parent)
        else:
            # If the parent has space, just save it.
            self._write_node(parent)

    def _split_internal_node(self, node):
        new_node = InternalNode(order=self.order)
        new_node.parent_page_id = node.parent_page_id
        mid_index = self.order // 2
        
        promoted_key = node.keys[mid_index]
        
        new_node.keys = node.keys[mid_index + 1:]
        new_node.children = node.children[mid_index + 1:]
        
        node.keys = node.keys[:mid_index]
        node.children = node.children[:mid_index + 1]
        
        self._write_node(new_node)
        self._write_node(node)
        
        for child_id in new_node.children:
            child = self._read_node(child_id)
            child.parent_page_id = new_node.page_id
            self._write_node(child)
            
        self._insert_in_parent(node, promoted_key, new_node)

    def search(self, key):
        if self.root_page_id is None: return None
        leaf = self._find_leaf(key)
        
        # Use bisect_left for a faster O(log n) search within the node
        idx = bisect.bisect_left(leaf.keys, key)
        
        # Check if the key at that index is the one we're looking for
        if idx < len(leaf.keys) and leaf.keys[idx] == key:
            return leaf.values[idx]
        
        return None

    def scan(self, start_key, end_key):
        results = []
        if self.root_page_id is None: return results
        leaf = self._find_leaf(start_key)
        while leaf is not None:
            for i, key in enumerate(leaf.keys):
                if key >= start_key:
                    if key <= end_key:
                        results.append((key, leaf.values[i]))
                    else:
                        return results
            if leaf.next_leaf_page_id:
                leaf = self._read_node(leaf.next_leaf_page_id)
            else:
                leaf = None
        return results

# ==============================================================================
# MAIN EXECUTION SCRIPT
# ==============================================================================
def main():
    # 1. Index Construction
    print("--- 1. Index Construction ---")
    
    # Add this check
    if not os.path.exists(DATASET_FILE):
        print(f"Error: Dataset file not found at '{DATASET_FILE}'")
        return
        
    tree = BPlusTree(INDEX_FILE, order=ORDER)
    build_time = 0
    # Define the record format again so the script knows how to read the .dat file
    RECORD_FORMAT = 'q100s'
    RECORD_SIZE = struct.calcsize(RECORD_FORMAT)
    
    try:
        print(f"Building index from binary file '{DATASET_FILE}'...")
        start_time = time.time()
        
        with open(DATASET_FILE, 'rb') as f:
            i = 0
            while True:
                # Read one fixed-size chunk of binary data
                record_chunk = f.read(RECORD_SIZE)
                
                # If the chunk is empty, we've reached the end of the file
                if not record_chunk:
                    break
                
                # Unpack the binary data back into Python objects
                key, value_bytes = struct.unpack(RECORD_FORMAT, record_chunk)
                
                # Decode the value and remove padding
                value = value_bytes.decode('utf-8').strip('\x00')
                
                tree.insert(key, value)
                i += 1
                if (i) % 1000000 == 0:
                    print(f"  ...inserted {i:,} records.")

        end_time = time.time()
        build_time = end_time - start_time
        print(f"Index construction complete in {build_time:.2f} seconds.")

    except FileNotFoundError:
        print(f"Error: Binary data file '{DATASET_FILE}' not found.")
        print("Please run the 'convert_to_dat.py' script first.")
    except Exception as e:
        print(f"An error occurred during index construction: {e}")
    
    # 2. Updates
    print("\n--- 2. Updates ---")
    print("Performing a batch of inserts...")
    new_data = {9999999999: "new_val_1", 9999999998: "new_val_2"}
    for k, v in new_data.items():
        tree.insert(k, v)
    print("Verifying an update...")
    result = tree.search(9999999999)
    print(f"  Search for key 9999999999 -> Found: {'Yes' if result else 'No'}. Value: {result}")
    
    # 3. Reporting
    print("\n--- 3. Reporting ---")
    # Index Size on Disk
    index_size_mb = os.path.getsize(INDEX_FILE) / (1024 * 1024)
    print(f"Index Size on Disk: {index_size_mb:.2f} MB")
    
    # Estimated Node Fanout
    print(f"Node Fanout (Order): {ORDER}")

    # Timings
    print(f"Build Time: {build_time:.2f} seconds")
    
    # Point Lookup Latency
    lookup_keys = [123456, 789012, 345678] # Use keys that exist in your dataset
    start_time = time.time()
    for key in lookup_keys:
        tree.search(key)
    end_time = time.time()
    avg_latency_ms = ((end_time - start_time) / len(lookup_keys)) * 1000
    print(f"Point Lookup Latency: {avg_latency_ms:.4f} ms per lookup.")
    
    # Range Scan Throughput
    scan_start_key = 100000
    scan_end_key = 110000
    start_time = time.time()
    scan_results = tree.scan(scan_start_key, scan_end_key)
    end_time = time.time()
    scan_time = end_time - start_time
    throughput = len(scan_results) / scan_time if scan_time > 0 else 0
    print(f"Range Scan Throughput: Fetched {len(scan_results)} records in {scan_time:.4f}s ({throughput:.2f} records/sec).")
    # ==========================================================================
    # 4. Interactive Search (Add this entire block)
    # ==========================================================================
    print("\n--- 4. Interactive Search ---")
    while True:
        # Ask the user for a key
        user_input = input("Enter a key to search for (or 'quit' to exit): ")

        # Check if the user wants to exit
        if user_input.lower() in ['quit', 'exit']:
            print("Exiting.")
            break

        # Try to search for the key
        try:
            search_key = int(user_input)
            start_search_time = time.time()
            result = tree.search(search_key) # This calls your B+ Tree's search method
            end_search_time = time.time()
            latency = (end_search_time - start_search_time) * 1000 # in ms

            if result:
                print(f"  ✅ Found! Value: '{result}' (Search took {latency:.4f} ms)")
            else:
                print(f" Key not found. (Search took {latency:.4f} ms)")
        
        except ValueError:
            print(" Invalid input. Please enter an integer key.")
    # Cleanup
    tree.close()

if __name__ == "__main__":
    main()