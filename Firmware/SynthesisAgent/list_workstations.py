
import requests
import json

def list_all_workstations():
    """
    Fetches all workstation definitions from the API and prints their names and codes.
    """
    base_url = "http://114.214.215.131:8018/worker/workstation/definition/list"
    total = 0

    # 1. First call to get the total count of workstations
    try:
        print("Step 1: Fetching total workstation count...")
        # We only need the 'total', so fetch a small payload
        response = requests.get(base_url, params={"size": 1}, timeout=20)
        response.raise_for_status()
        data = response.json()
        total = data.get("total")
        if not total:
            print("Error: Could not retrieve total workstation count.")
            return
        print(f"Found {total} workstations in total.")
    except requests.exceptions.RequestException as e:
        print(f"Error fetching total count: {e}")
        return
    except json.JSONDecodeError:
        print("Error: Failed to decode JSON from the initial API response.")
        return

    # 2. Second call to get all workstations
    try:
        print(f"Step 2: Fetching all {total} workstations...")
        response = requests.get(base_url, params={"size": total}, timeout=60)
        response.raise_for_status()
        data = response.json()
        workstations = data.get("data")
        if not workstations:
            print("Error: No workstation data found in the API response.")
            return
    except requests.exceptions.RequestException as e:
        print(f"Error fetching all workstations: {e}")
        return
    except json.JSONDecodeError:
        print("Error: Failed to decode JSON from the main API response.")
        return

    # 3. Print the name and code for each workstation
    print("\n=== List of All Workstations ===")
    if workstations:
        for i, ws in enumerate(workstations):
            name = ws.get("name", "N/A")
            code = ws.get("code", "N/A")
            print(f"{i+1: >3}. Name: {name:<45} Code: {code}")
    print("\n================================")
    print(f"Successfully listed {len(workstations)} workstations.")


if __name__ == "__main__":
    list_all_workstations()
