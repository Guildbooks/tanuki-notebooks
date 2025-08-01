import csv
import json
import re
import time
import requests
import pandas as pd
import os
import glob
from collections import defaultdict

# --- Helper Functions ---

def max_columns_in_csv(filepath):
    """Determine the maximum number of columns in a CSV file."""
    with open(filepath, newline='') as f:
        reader = csv.reader(f)
        return max(len(row) for row in reader)

def load_csv_with_max_columns(filepath):
    """Load a CSV file using the Python engine and ensure uniform column count."""
    max_fields = max_columns_in_csv(filepath)
    return pd.read_csv(
        filepath,
        header=None,
        engine='python',
        names=range(max_fields),
        on_bad_lines='skip'  # Skip lines with too many fields
    )

# Function to consolidate CSV contents
def consolidate_csv_files(folder_path="utilities/workshop_parts"):
    item_quantities = {}
    for f in glob.glob(os.path.join(folder_path, "*.csv")):
        with open(f, encoding='utf-8') as x:
            for l in x:
                p = l.strip().split(',', 1)
                if len(p) == 2:
                    try: item_quantities[p[0].strip()] = item_quantities.get(p[0].strip(), 0) + int(p[1])
                    except: continue
    if not item_quantities: return None
    df = pd.DataFrame([[k, v] for k, v in item_quantities.items()], columns=["Item", "Quantity"]).sort_values("Item")

    r, g = load_csv_with_max_columns(os.path.join("utilities", "recipe_book.csv")), load_csv_with_max_columns(os.path.join("utilities", "recipe_gathering.csv"))
    recipes, gather = {}, {row[0]: row[1] for _, row in g.iterrows()}
    for _, row in r.iterrows():
        recipes[row[0]] = [(row[i], float(row[i + 1])) for i in range(1, r.shape[1], 2) if not pd.isna(row[i])]

    def comp(it, m=1):
        if it in recipes:
            res = []
            for ing, qty in recipes[it]:
                opts = [o.strip() for o in str(ing).split('|')]
                res.append([comp(o, qty * m) for o in opts] if len(opts) > 1 else comp(opts[0], qty * m))
            return res
        if gather.get(it, '').lower() == "crystal": return {it: m}
        return {}

    def flat(g):
        if isinstance(g, dict): return [f"{k} x {int(v)}" for k, v in g.items()]
        if isinstance(g, list) and all(isinstance(x, dict) and x for x in g): return [" | ".join(flat(x)[0] for x in g)]
        out = []
        for sub in g:
            out += flat(sub)
        return out

    df["Crystals Needed"] = [" & ".join(flat(comp(row["Item"], row["Quantity"]))) for _, row in df.iterrows()]
    df[["Item", "Quantity"]].to_csv(os.path.join("utilities", "workshop_output.csv"), index=False, header=False)
    return df


# --- Gathering List Generation ---

def generate_gathering_list(total_csv, recipe_book_csv, recipe_gathering_csv, output_csv):
    """
    Generate the comprehensive list of base ingredients needed (gathering list).
    
    - total_csv: path to total_shark_class_sub_parts.csv (top-level items)
    - recipe_book_csv: path to recipe_book.csv (crafting recipes)
    - recipe_gathering_csv: path to recipe_gathering.csv (gathering locations)
    - output_csv: file name to write the final gathering list.
    
    Returns the resulting DataFrame.
    """
    df_total = load_csv_with_max_columns(total_csv)
    df_recipe_book = load_csv_with_max_columns(recipe_book_csv)
    df_recipe_gathering = load_csv_with_max_columns(recipe_gathering_csv)

    max_fields_recipe_book = df_recipe_book.shape[1]
    recipes = {}
    for _, row in df_recipe_book.iterrows():
        product = row[0]
        ingredients = []
        for i in range(1, max_fields_recipe_book, 2):
            if pd.isna(row[i]):
                break
            ingredient = row[i]
            qty = float(row[i + 1]) if i + 1 < max_fields_recipe_book and not pd.isna(row[i + 1]) else 0
            ingredients.append((ingredient, qty))
        recipes[product] = ingredients

    top_level = {row[0]: float(row[1]) for _, row in df_total.iterrows()}

    requirements = defaultdict(float)

    def compute_requirements(item, multiplier):
        if item in recipes:
            for ingredient, qty in recipes[item]:
                # Handle alternative ingredients split by '|'
                options = [opt.strip() for opt in str(ingredient).split('|')]
                for opt in options:
                    compute_requirements(opt, qty * multiplier / len(options))
        else:
            requirements[item] += multiplier

    for product, qty in top_level.items():
        compute_requirements(product, qty)

    df_requirements = pd.DataFrame(list(requirements.items()), columns=["Ingredient", "Total Quantity"])

    df_recipe_gathering.rename(columns={0: "Ingredient", 1: "Method"}, inplace=True)

    def combine_location(row):
        return ", ".join(
            str(v).strip() for v in row[2:] if pd.notna(v) and str(v).strip()
        )

    df_recipe_gathering["Location Info"] = df_recipe_gathering.apply(combine_location, axis=1)
    df_recipe_gathering = df_recipe_gathering[["Ingredient", "Method", "Location Info"]]

    df_output = pd.merge(df_requirements, df_recipe_gathering, on="Ingredient", how="left")

    # Assign "unknown" to Method where it's missing
    df_output["Method"] = df_output["Method"].fillna("unknown")
    df_output["Location Info"] = df_output["Location Info"].fillna("")

    df_output = df_output.sort_values("Ingredient")
    df_output.to_csv(output_csv, index=False)
    return df_output



# --- Crafting Recipes List ---

def get_crafting_recipes(total_csv):
    """
    Generate the list of crafting recipes from a totalized parts CSV.
    
    Returns a DataFrame with the crafted product list sorted alphabetically.
    """
    df_crafting = load_csv_with_max_columns(total_csv)
    df_crafting = df_crafting.sort_values(by=0)
    df_crafting.rename(columns={0: "Product", 1: "Required Quantity"}, inplace=True)
    return df_crafting

"""
# --- Market Data Fetching ---

def fetch_market_data(item_id, world, market_columns):
    # Query the Universalis API for market data on a given item.
    # Returns a dictionary with market data (or None values on failure).
    
    url = f"https://universalis.app/api/v2/aggregated/{world}/{item_id}"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            if "results" in data and len(data["results"]) > 0:
                result = data["results"][0]
                return {
                    "minListing_world": result.get("nq", {}).get("minListing", {}).get("world", {}).get("price"),
                    "minListing_dc": result.get("nq", {}).get("minListing", {}).get("dc", {}).get("price"),
                    "recentPurchase_world": result.get("nq", {}).get("recentPurchase", {}).get("world", {}).get("price"),
                    "recentPurchase_dc": result.get("nq", {}).get("recentPurchase", {}).get("dc", {}).get("price"),
                    "averageSalePrice_dc": result.get("nq", {}).get("averageSalePrice", {}).get("dc", {}).get("price"),
                    "dailySaleVelocity_dc": result.get("nq", {}).get("dailySaleVelocity", {}).get("dc", {}).get("quantity"),
                }
            else:
                print(f"No results found for item ID {item_id}")
        else:
            print(f"Error fetching data for item ID {item_id}. Status code: {response.status_code}")
    except Exception as e:
        print(f"Exception for item ID {item_id}: {e}")
    return {col: None for col in market_columns}

def fetch_market_data_for_subparts(gathering_csv, crafting_csv, item_ids_json, output_csv, world="Seraph"):
    
    # Combine items from the gathering list and the crafting recipes list, look up their IDs,
    # query the Universalis API for market data, and write the results to output_csv.
    
    # Load the gathering list.
    # Here we assume gathering_csv already has headers, so we use the default header.
    df_gathering = pd.read_csv(gathering_csv).copy()
    df_gathering = df_gathering[["Ingredient"]].copy()
    df_gathering.rename(columns={"Ingredient": "Item Name"}, inplace=True)
    df_gathering["Category"] = "Gathering"

    # Load the crafting recipes using the helper function to handle variable columns.
    df_crafting = load_csv_with_max_columns(crafting_csv).copy()
    # The first column in the crafting CSV (e.g., recipe_book.csv) is the crafted product.
    df_crafting = df_crafting[[0]].copy()
    df_crafting.rename(columns={0: "Item Name"}, inplace=True)
    df_crafting["Category"] = "Crafting"

    # Combine the two lists and remove duplicates.
    df_combined = pd.concat([df_gathering, df_crafting], ignore_index=True)
    df_combined = df_combined.drop_duplicates(subset=["Item Name"])

    # Load item ID mapping from JSON.
    with open(item_ids_json, "r", encoding="utf-8") as f:
        item_json = json.load(f)
    item_mapping = {}
    for item_id, names in item_json.items():
        en_name = names.get("en", "").strip().lower()
        if en_name:
            item_mapping[en_name] = item_id

    # Helper functions for cleaning names and looking up IDs.
    def clean_item_name(name):
        return name.lower().strip()

    def get_item_id(name):
        cleaned = clean_item_name(name)
        if cleaned in item_mapping:
            return item_mapping[cleaned]
        else:
            print(f"Error: No ID found for item '{name}' (cleaned as '{cleaned}').")
            return None

    df_combined["Item ID"] = df_combined["Item Name"].apply(get_item_id)

    # Initialize market data columns.
    market_columns = [
        "minListing_world", 
        "minListing_dc", 
        "recentPurchase_world", 
        "recentPurchase_dc", 
        "averageSalePrice_dc", 
        "dailySaleVelocity_dc"
    ]
    for col in market_columns:
        df_combined[col] = None

    # Fetch market data for each item.
    for idx, row in df_combined.iterrows():
        item_id = row["Item ID"]
        if item_id is not None:
            market_data = fetch_market_data(item_id, world, market_columns)
            for key, value in market_data.items():
                df_combined.at[idx, key] = value
            time.sleep(0.5)
        else:
            print(f"Skipping market query for '{row['Item Name']}' due to missing ID.")

    df_combined.to_csv(output_csv, index=False)
    return df_combined
"""


def print_recipe_tree(total_csv, recipe_book_csv, recipe_gathering_csv):
    """
    Recursively prints each top‐level product (from total_csv) as a tree:
      ├── IngredientA (x qty)
      │   ├── SubIngredient1 (x qty*…)
      │   └── SubIngredient2 (x qty*…)
      └── IngredientB (x qty)
          └── … etc …
    Leaf nodes show their gathering Method and Location Info in brackets.

    total_csv: path to CSV with top‐level items and quantities.
    recipe_book_csv: path to CSV with crafting recipes (product → ingredient, qty, …).
    recipe_gathering_csv: path to CSV mapping ingredient → Method + locations.
    """

    # 1) Build top‐level dict: {product_name: quantity}
    df_total = load_csv_with_max_columns(total_csv)
    top_level = {row[0]: float(row[1]) for _, row in df_total.iterrows()}

    # 2) Build recipes dict: {product: [(ingredient, qty), …]}
    df_recipe = load_csv_with_max_columns(recipe_book_csv)
    max_fields = df_recipe.shape[1]
    recipes = {}
    for _, row in df_recipe.iterrows():
        product = row[0]
        ingredients = []
        for i in range(1, max_fields, 2):
            if pd.isna(row[i]):
                break
            ing = row[i]
            qty = float(row[i + 1]) if (i + 1 < max_fields and not pd.isna(row[i + 1])) else 0.0
            ingredients.append((ing, qty))
        recipes[product] = ingredients

    # 3) Build gathering info: {ingredient: (method, location_info_string)}
    df_gather = load_csv_with_max_columns(recipe_gathering_csv)
    df_gather.rename(columns={0: "Ingredient", 1: "Method"}, inplace=True)

    def _combine_location(row):
        return ", ".join(
            str(v).strip() for v in row[2:] if pd.notna(v) and str(v).strip()
        )

    gather_info = {}
    for _, row in df_gather.iterrows():
        ing = row["Ingredient"]
        method = row["Method"]
        loc = _combine_location(row)
        gather_info[ing] = (method, loc)

    # 4) Recursive printer
    def _print_node(item_name, qty, prefix="", is_last=False):
        branch = "└── " if is_last else "├── "
        line = prefix + branch + f"{item_name} (x {qty:g})"

        if item_name not in recipes:
            # leaf: append gathering info if available
            if item_name in gather_info:
                m, loc = gather_info[item_name]
                line += f"  [{m} @ {loc}]"
            print(line)
        else:
            print(line)
            children = recipes[item_name]
            for idx, (child, child_qty) in enumerate(children):
                last_child = (idx == len(children) - 1)
                next_prefix = prefix + ("    " if is_last else "│   ")
                _print_node(child, child_qty * qty, prefix=next_prefix, is_last=last_child)

    # 5) Top‐level iteration
    print("=== Recipe Breakdown ===")
    items = list(top_level.items())
    for idx, (prod, qty) in enumerate(items):
        last_prod = (idx == len(items) - 1)
        _print_node(prod, qty, prefix="", is_last=last_prod)