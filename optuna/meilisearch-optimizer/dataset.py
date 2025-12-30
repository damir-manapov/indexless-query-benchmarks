#!/usr/bin/env python3
"""
Generate synthetic e-commerce product dataset for Meilisearch benchmarks.

Usage:
    python dataset.py --count 500000 --output products.json
    python dataset.py --count 500000 --output products.ndjson --format ndjson
"""

import argparse
import json
import random
import sys
from pathlib import Path

# Product categories and brands
CATEGORIES = [
    "Laptops",
    "Smartphones",
    "Tablets",
    "Headphones",
    "Cameras",
    "TVs",
    "Gaming",
    "Wearables",
    "Audio",
    "Accessories",
]

BRANDS = [
    "Apple",
    "Samsung",
    "Sony",
    "LG",
    "Dell",
    "HP",
    "Lenovo",
    "Asus",
    "Acer",
    "Microsoft",
    "Google",
    "Bose",
    "JBL",
    "Canon",
    "Nikon",
    "Nintendo",
    "Razer",
    "Logitech",
    "Anker",
    "Belkin",
]

# Adjectives for product titles
ADJECTIVES = [
    "Pro",
    "Ultra",
    "Max",
    "Plus",
    "Lite",
    "Mini",
    "Elite",
    "Premium",
    "Advanced",
    "Essential",
    "Compact",
    "Wireless",
    "Portable",
    "Smart",
    "Digital",
]

# Product name templates per category
PRODUCT_TEMPLATES = {
    "Laptops": [
        "{brand} {adj} Laptop {num}",
        "{brand} Notebook {adj} {num}",
        "{brand} {adj} Book {num}",
    ],
    "Smartphones": [
        "{brand} Phone {adj} {num}",
        "{brand} {adj} {num}",
        "{brand} Mobile {adj} {num}",
    ],
    "Tablets": [
        "{brand} Tab {adj} {num}",
        "{brand} Pad {adj} {num}",
        "{brand} {adj} Tablet {num}",
    ],
    "Headphones": [
        "{brand} {adj} Buds {num}",
        "{brand} {adj} Headphones",
        "{brand} {adj} Earbuds {num}",
    ],
    "Cameras": [
        "{brand} {adj} Camera {num}",
        "{brand} {adj} DSLR {num}",
        "{brand} Mirrorless {adj} {num}",
    ],
    "TVs": [
        '{brand} {num}" {adj} TV',
        '{brand} {adj} {num}" Smart TV',
        '{brand} OLED {num}" {adj}',
    ],
    "Gaming": [
        "{brand} {adj} Controller",
        "{brand} Gaming {adj} {num}",
        "{brand} {adj} Console",
    ],
    "Wearables": [
        "{brand} Watch {adj} {num}",
        "{brand} {adj} Band {num}",
        "{brand} Fitness {adj} {num}",
    ],
    "Audio": [
        "{brand} {adj} Speaker",
        "{brand} Soundbar {adj}",
        "{brand} {adj} Home Audio",
    ],
    "Accessories": [
        "{brand} {adj} Charger",
        "{brand} {adj} Cable",
        "{brand} {adj} Case",
        "{brand} {adj} Stand",
    ],
}

# Description templates
DESCRIPTION_TEMPLATES = [
    "The {title} delivers exceptional performance with cutting-edge technology. "
    "Features include {feature1}, {feature2}, and {feature3}. "
    "Perfect for {use_case}.",
    "Experience the next level of {category} with the {title}. "
    "Equipped with {feature1} and {feature2}, this device offers "
    "unmatched {benefit} for {use_case}.",
    "Introducing the {title} - designed for those who demand the best. "
    "With {feature1}, {feature2}, and {feature3}, enjoy superior {benefit}. "
    "Ideal for {use_case}.",
]

FEATURES = [
    "fast charging",
    "long battery life",
    "high-resolution display",
    "noise cancellation",
    "wireless connectivity",
    "AI-powered features",
    "sleek design",
    "durable build",
    "water resistance",
    "voice control",
    "multi-device support",
    "cloud sync",
    "advanced sensors",
    "precision controls",
    "immersive sound",
]

BENEFITS = [
    "performance",
    "quality",
    "experience",
    "productivity",
    "entertainment",
    "convenience",
    "reliability",
    "versatility",
]

USE_CASES = [
    "professionals",
    "gamers",
    "content creators",
    "music lovers",
    "everyday use",
    "travel",
    "home entertainment",
    "fitness enthusiasts",
    "remote work",
    "students",
]


def generate_product(product_id: int) -> dict:
    """Generate a single product."""
    category = random.choice(CATEGORIES)
    brand = random.choice(BRANDS)
    adj = random.choice(ADJECTIVES)
    num = random.randint(1, 20)

    # Generate title
    template = random.choice(PRODUCT_TEMPLATES[category])
    title = template.format(brand=brand, adj=adj, num=num)

    # Generate description
    desc_template = random.choice(DESCRIPTION_TEMPLATES)
    features = random.sample(FEATURES, 3)
    description = desc_template.format(
        title=title,
        category=category.lower(),
        feature1=features[0],
        feature2=features[1],
        feature3=features[2],
        benefit=random.choice(BENEFITS),
        use_case=random.choice(USE_CASES),
    )

    # Generate price based on category
    price_ranges = {
        "Laptops": (500, 3500),
        "Smartphones": (200, 1500),
        "Tablets": (150, 1200),
        "Headphones": (30, 500),
        "Cameras": (300, 3000),
        "TVs": (200, 5000),
        "Gaming": (30, 600),
        "Wearables": (50, 800),
        "Audio": (50, 1500),
        "Accessories": (10, 150),
    }
    min_price, max_price = price_ranges[category]
    price = round(random.uniform(min_price, max_price), 2)

    return {
        "id": product_id,
        "title": title,
        "description": description,
        "brand": brand,
        "category": category,
        "price": price,
        "rating": round(random.uniform(3.0, 5.0), 1),
        "reviews_count": random.randint(0, 5000),
        "in_stock": random.random() > 0.1,  # 90% in stock
    }


def generate_dataset(count: int) -> list[dict]:
    """Generate a dataset of products."""
    print(f"Generating {count:,} products...")
    products = []
    for i in range(1, count + 1):
        products.append(generate_product(i))
        if i % 100000 == 0:
            print(f"  Generated {i:,} products...")
    return products


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic product dataset")
    parser.add_argument(
        "--count", "-c", type=int, default=500000, help="Number of products to generate"
    )
    parser.add_argument(
        "--output", "-o", type=str, default="products.ndjson", help="Output file path"
    )
    parser.add_argument(
        "--format",
        "-f",
        type=str,
        choices=["json", "ndjson"],
        default="ndjson",
        help="Output format",
    )
    parser.add_argument("--seed", "-s", type=int, default=42, help="Random seed")

    args = parser.parse_args()
    random.seed(args.seed)

    products = generate_dataset(args.count)

    output_path = Path(args.output)
    print(f"Writing to {output_path}...")

    if args.format == "json":
        with open(output_path, "w") as f:
            json.dump(products, f)
    else:  # ndjson
        with open(output_path, "w") as f:
            for product in products:
                f.write(json.dumps(product) + "\n")

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"Done! File size: {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
