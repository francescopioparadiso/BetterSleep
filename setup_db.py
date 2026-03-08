#!/usr/bin/env python3
"""
Database setup script that uses REST API to initialize test data
"""
import requests
import time
import json

# Configuration
USER_SERVICE_URL = "http://127.0.0.1:9095"
CATALOG_URL = "http://127.0.0.1:8080"
MAX_RETRIES = 120  # Increased from 30
RETRY_DELAY = 2    # Increased from 1

def wait_for_service(url, name):
    """Wait for a service to be ready"""
    print(f"Waiting for {name} to be ready at {url}...")
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(f"{url}/", timeout=2)
            if response.status_code in [200, 404, 405]:  # 405 is Method Not Allowed, which means service is up
                print(f"✓ {name} is ready!")
                return True
        except requests.exceptions.RequestException:
            pass
        
        if attempt < MAX_RETRIES - 1:
            time.sleep(RETRY_DELAY)
            print(f"  Attempt {attempt + 1}/{MAX_RETRIES}...")
    
    print(f"✗ {name} not ready after {MAX_RETRIES} attempts")
    return False

def api_call(method, endpoint, data=None):
    """Make an API call to user service"""
    url = f"{USER_SERVICE_URL}/{endpoint}"
    try:
        if method == "POST":
            response = requests.post(url, json=data, timeout=5)
        elif method == "PUT":
            response = requests.put(url, json=data, timeout=5)
        elif method == "GET":
            response = requests.get(url, timeout=5)
        else:
            return None
        
        if response.status_code in [200, 201]:
            return response.json()
        else:
            print(f"  Error: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"  Exception: {e}")
        return None

def main():
    print("=" * 60)
    print("Database Setup - Initializing Test Data")
    print("=" * 60)
    
    # Wait for services
    if not wait_for_service(USER_SERVICE_URL, "User Service"):
        print("Failed to connect to User Service")
        return False
    
    # Test data
    users = [
        {"email": "francesco@email.com", "password": "password"},
        {"email": "antonino@email.com", "password": "password"}
    ]
    
    houses_data = [
        {"name": "Francesco House"},
        {"name": "Antonino House"}
    ]
    
    rooms_data = [
        # Francesco's house (house_id=1)
        [
            {"house_id": 1, "name": "Master Bedroom"},
            {"house_id": 1, "name": "Guest Bedroom"},
            {"house_id": 1, "name": "Living Room"}
        ],
        # Antonino's house (house_id=2)
        [
            {"house_id": 2, "name": "Master Bedroom"},
            {"house_id": 2, "name": "Office"},
            {"house_id": 2, "name": "Bedroom 2"}
        ]
    ]
    
    invitations_data = [
        {"house_id": 1, "email": "test1@email.com"},
        {"house_id": 2, "email": "test2@email.com"}
    ]
    
    user_ids = {}
    house_ids = {}
    room_ids = {1: [], 2: []}
    
    try:
        # STEP 1: Sign up users
        print("\n[1/6] Creating users...")
        for user in users:
            print(f"  Signing up {user['email']}...", end=" ")
            result = api_call("POST", "signup", user)
            if result and "id" in result:
                user_ids[user["email"]] = result["id"]
                print(f"✓ (ID: {result['id']})")
            else:
                if result and result.get("status") == "error" and "already exists" in result.get("message", ""):
                    print("✓ (Already exists)")
                else:
                    print("✗")
        
        if len(user_ids) < 2:
            print("  Warning: Could not create all users")
        
        # Get user IDs from API if not created
        if not user_ids:
            print("  Attempting to retrieve user IDs...")
            # We need to login to get IDs
            for user in users:
                print(f"  Logging in {user['email']}...", end=" ")
                result = api_call("POST", "login", user)
                if result and "id" in result:
                    user_ids[user["email"]] = result["id"]
                    print(f"✓ (ID: {result['id']})")
                else:
                    print("✗")
        
        # STEP 2: Create houses
        print("\n[2/6] Creating houses...")
        for i, house in enumerate(houses_data, 1):
            print(f"  Creating {house['name']}...", end=" ")
            result = api_call("POST", "addHouse", house)
            if result and "id" in result:
                house_ids[i] = result["id"]
                print(f"✓ (ID: {result['id']})")
            else:
                print("✗")
        
        # STEP 3: Create rooms
        print("\n[3/6] Creating rooms...")
        for house_num, rooms in enumerate(rooms_data, 1):
            for room in rooms:
                print(f"  Creating {room['name']} in house {house_num}...", end=" ")
                result = api_call("POST", "addRoom", room)
                if result and "id" in result:
                    room_ids[house_num].append(result["id"])
                    print(f"✓ (ID: {result['id']})")
                else:
                    print("✗")
        
        # STEP 4: Assign rooms to users (first 2 rooms per user)
        print("\n[4/6] Assigning rooms to users...")
        user_email_list = list(user_ids.keys())
        for user_idx, (house_num, rooms) in enumerate(enumerate(room_ids.values(), 1), 0):
            if user_idx >= len(user_email_list):
                break
            user_email = user_email_list[user_idx]
            user_id = user_ids[user_email]
            house_id = house_ids.get(house_num)
            
            # Assign first 2 rooms
            for room_idx, room_id in enumerate(rooms[:2]):
                print(f"  Assigning room {room_id} to {user_email}...", end=" ")
                result = api_call("PUT", "assignRoom", {
                    "room_id": room_id,
                    "user_id": user_id,
                    "house_id": house_id
                })
                if result:
                    print("✓")
                else:
                    print("✗")
        
        # STEP 5: Set one room as active per user
        print("\n[5/6] Setting active rooms...")
        user_email_list = list(user_ids.keys())
        for user_idx, (house_num, rooms) in enumerate(enumerate(room_ids.values(), 1), 0):
            if user_idx >= len(user_email_list):
                break
            user_email = user_email_list[user_idx]
            user_id = user_ids[user_email]
            
            if len(rooms) > 0:
                room_id = rooms[0]  # Set first room as active
                print(f"  Setting room {room_id} as active for {user_email}...", end=" ")
                result = api_call("PUT", "setActiveRoom", {
                    "room_id": room_id,
                    "user_id": user_id
                })
                if result:
                    print("✓")
                else:
                    print("✗")
        
        # STEP 6: Create invitations
        print("\n[6/6] Creating invitations...")
        for invitation in invitations_data:
            house_name = houses_data[invitation["house_id"] - 1]["name"]
            print(f"  Inviting {invitation['email']} to {house_name}...", end=" ")
            result = api_call("POST", "addInvitation", invitation)
            if result:
                print("✓")
            else:
                print("✗")
        
        print("\n" + "=" * 60)
        print("✓ Setup completed!")
        print("=" * 60)
        return True
        
    except Exception as e:
        print(f"\n✗ Setup failed: {e}")
        return False

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
