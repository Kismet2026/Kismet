"""
Seed 150 fake user profiles into Kismet DynamoDB tables.
Writes to both kismet-profiles and kismet-discovery so discovery/swipe works immediately.

Usage:
    python3 scripts/seed_profiles.py              # dry run (print only)
    python3 scripts/seed_profiles.py --execute     # actually write to DynamoDB
    python3 scripts/seed_profiles.py --delete      # remove all seeded profiles
"""

import argparse
import json
import random
import uuid
from datetime import datetime, timezone
from typing import Any

import boto3

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
REGION = "us-east-1"
PROFILES_TABLE = "kismet-profiles"
DISCOVERY_TABLE = "kismet-discovery"
NUM_PROFILES = 150
SEED_PREFIX = "seed-"  # all seeded userIds start with this for easy cleanup

# ---------------------------------------------------------------------------
# Bay Area cities with approximate coordinates
# ---------------------------------------------------------------------------
BAY_AREA_CITIES = [
    ("San Francisco", 37.7749, -122.4194),
    ("San Jose", 37.3382, -121.8863),
    ("Oakland", 37.8044, -122.2712),
    ("Palo Alto", 37.4419, -122.1430),
    ("Mountain View", 37.3861, -122.0839),
    ("Sunnyvale", 37.3688, -122.0363),
    ("Santa Clara", 37.3541, -121.9552),
    ("Berkeley", 37.8716, -122.2727),
    ("Fremont", 37.5485, -121.9886),
    ("Redwood City", 37.4852, -122.2364),
    ("Cupertino", 37.3230, -122.0322),
    ("Daly City", 37.6879, -122.4702),
    ("San Mateo", 37.5630, -122.3255),
    ("Milpitas", 37.4323, -121.8996),
    ("Walnut Creek", 37.9101, -122.0652),
]

# ---------------------------------------------------------------------------
# Name pools
# ---------------------------------------------------------------------------
FEMALE_NAMES = [
    "Sophia", "Emma", "Olivia", "Ava", "Isabella", "Mia", "Luna", "Chloe",
    "Aria", "Ella", "Scarlett", "Lily", "Zoe", "Nora", "Riley", "Hazel",
    "Maya", "Ivy", "Willow", "Aurora", "Jade", "Violet", "Ruby", "Stella",
    "Clara", "Elena", "Alice", "Iris", "Lydia", "Fiona", "Nina", "Rosa",
    "Mei", "Yuki", "Aisha", "Priya", "Ananya", "Sakura", "Hana", "Wei",
    "Jing", "Xiaoli", "Suki", "Rina", "Kavya", "Devi", "Amara", "Zara",
    "Naomi", "Lena", "Kira", "Thea", "Freya", "Elise", "Vera", "Camille",
]

MALE_NAMES = [
    "Liam", "Noah", "Oliver", "James", "Ethan", "Lucas", "Mason", "Logan",
    "Alex", "Daniel", "Henry", "Jack", "Owen", "Leo", "Ryan", "Kai",
    "Max", "Theo", "Finn", "Cole", "Miles", "Dean", "Seth", "Blake",
    "Ravi", "Arjun", "Vikram", "Sanjay", "Kenji", "Hiroshi", "Takeshi", "Ryo",
    "Wei", "Jun", "Chen", "Hao", "Ming", "Tao", "Yong", "Bo",
    "Marcus", "Andre", "Derek", "Caleb", "Nolan", "Grant", "Troy", "Reid",
    "Felix", "Oscar", "Hugo", "Jasper", "Atlas", "Ezra", "Milo", "Ivan",
]

NB_NAMES = [
    "Jordan", "Avery", "Quinn", "Sage", "River", "Rowan", "Morgan", "Casey",
    "Ash", "Skyler", "Dakota", "Finley", "Reese", "Emery", "Kai", "Drew",
]

LAST_NAMES = [
    "Chen", "Wang", "Li", "Zhang", "Liu", "Yang", "Huang", "Wu",
    "Patel", "Shah", "Kumar", "Singh", "Sharma", "Gupta", "Mehta", "Joshi",
    "Kim", "Park", "Lee", "Choi", "Tanaka", "Sato", "Suzuki", "Nakamura",
    "Smith", "Johnson", "Brown", "Davis", "Wilson", "Taylor", "Anderson", "Moore",
    "Garcia", "Rodriguez", "Martinez", "Lopez", "Gonzalez", "Hernandez",
    "O'Brien", "Murphy", "Kelly", "Sullivan", "Nguyen", "Tran", "Vo", "Le",
]

# ---------------------------------------------------------------------------
# Bio and interest pools
# ---------------------------------------------------------------------------
OCCUPATIONS = [
    "software engineer", "product manager", "data scientist", "UX designer",
    "startup founder", "grad student", "marketing manager", "artist",
    "photographer", "nurse", "teacher", "financial analyst", "consultant",
    "researcher", "barista & musician", "yoga instructor", "chef",
    "architect", "journalist", "physical therapist", "lawyer",
    "graphic designer", "mechanical engineer", "biotech researcher",
    "real estate agent", "veterinarian", "social worker", "DJ",
]

BIO_TEMPLATES = [
    "{occ} in {city}. {hobby}. Looking for someone who {looking}.",
    "{hobby}. {occ} by day. {quirk}.",
    "Transplant from {origin}. {occ}. {hobby}. {quirk}.",
    "{occ}. {hobby}. {looking_short}.",
    "Just a {occ} who {hobby_verb}. {quirk}.",
    "{quirk}. {occ} @ {company}. {hobby}.",
    "{hobby}. {occ}. Probably {guilty_pleasure} right now.",
    "Life's too short to {anti}. {occ}. {hobby}.",
]

HOBBIES = [
    "Love hiking the Marin Headlands", "Weekend rock climber at Castle Rock",
    "Obsessed with sourdough", "Amateur ceramicist", "Trail runner",
    "Board game night enthusiast", "Live music addict", "Film photography nerd",
    "Salsa dancing on weekends", "Bookworm (sci-fi mostly)",
    "Homebrewer", "Surfing at Pacifica when the waves hit",
    "Hot springs explorer", "Farmers market regular",
    "Muay Thai after work", "Piano player", "Weekend backpacker",
    "Street food tour guide", "Bouldering at Dogpatch",
    "Watercolor painter", "Vinyl collector", "Plant parent to 30+ plants",
    "Dim sum connoisseur", "Mountain biker", "Open mic comedian",
    "Tarot reader for fun", "Thrift store treasure hunter",
]

HOBBY_VERBS = [
    "spends too much on coffee", "hikes every weekend", "cooks way too much pasta",
    "reads on BART", "bikes to work rain or shine", "runs the Embarcadero at dawn",
    "collects vintage synths", "watches too many documentaries",
]

QUIRKS = [
    "Can recommend a taco spot in every neighborhood",
    "Will beat you at Mario Kart",
    "Speaks 3 languages badly",
    "My dog has more followers than me",
    "I have strong opinions about coffee",
    "Ask me about my sourdough starter",
    "Recovering tech bro",
    "Sunset chaser",
    "Still figuring out adulting",
    "I make playlists for everything",
    "Perpetually planning my next trip",
    "I have a spreadsheet for restaurants",
    "Chaotic good energy",
    "Morning person (sorry)",
    "Night owl who's trying to change",
]

LOOKING_FOR = [
    "enjoys long walks and good conversation",
    "can keep up on a trail",
    "appreciates a home-cooked meal",
    "doesn't take life too seriously",
    "wants to explore the city together",
    "likes spontaneous weekend trips",
    "can debate movies for hours",
]

LOOKING_SHORT = [
    "Here for genuine connections",
    "Looking for my adventure partner",
    "Seeking someone to split appetizers with",
    "Hoping to find my person",
    "Ready for something real",
    "Let's grab coffee and see what happens",
]

ORIGINS = [
    "NYC", "LA", "Chicago", "Seattle", "Austin", "Boston", "Portland",
    "Denver", "Atlanta", "Miami", "Minneapolis", "Taipei", "Seoul",
    "Tokyo", "Mumbai", "Shanghai", "London", "Toronto", "Vancouver",
]

COMPANIES = [
    "a startup you haven't heard of", "a FAANG", "a biotech",
    "a fintech", "a nonprofit", "myself", "a hospital", "a school",
]

GUILTY_PLEASURES = [
    "binge-watching reality TV", "eating ramen at midnight",
    "doom-scrolling", "online shopping", "napping",
    "playing video games", "snacking on cheese",
]

ANTI = [
    "swipe without saying hi", "eat bad sushi", "skip dessert",
    "not pet every dog you see", "take life too seriously",
]

INTERESTS_POOL = [
    "hiking", "cooking", "photography", "travel", "yoga", "running",
    "reading", "music", "art", "coffee", "wine", "baking",
    "surfing", "climbing", "cycling", "camping", "skiing", "tennis",
    "basketball", "soccer", "volleyball", "dancing", "meditation",
    "gardening", "gaming", "anime", "film", "theater", "karaoke",
    "boardgames", "trivia", "dogs", "cats", "foodie", "brunch",
    "tech", "startups", "design", "fitness", "crossfit", "pilates",
    "pottery", "writing", "podcasts", "craft beer", "cocktails",
    "museums", "concerts", "festivals", "road trips", "astrology",
]


def generate_bio(city: str) -> str:
    occ = random.choice(OCCUPATIONS)
    template = random.choice(BIO_TEMPLATES)
    bio = template.format(
        occ=occ,
        city=city,
        hobby=random.choice(HOBBIES),
        hobby_verb=random.choice(HOBBY_VERBS),
        quirk=random.choice(QUIRKS),
        looking=random.choice(LOOKING_FOR),
        looking_short=random.choice(LOOKING_SHORT),
        origin=random.choice(ORIGINS),
        company=random.choice(COMPANIES),
        guilty_pleasure=random.choice(GUILTY_PLEASURES),
        anti=random.choice(ANTI),
    )
    return bio[:500]


# ---------------------------------------------------------------------------
# Pinned birthdates — these MUST appear in the seed pool so BaZi demo works.
# User A (1999-08-21, male): top BaZi matches
# User B (1994-11-02, male): top BaZi matches
# ---------------------------------------------------------------------------
PINNED_BIRTHDATES = [
    # User A (1999-08-21) matches — scores 83-89
    "2003-02-26",  # score 89
    "1994-02-13",  # score 89
    "2003-02-06",  # score 89
    "1994-02-23",  # score 89
    "1995-02-08",  # score 87
    "1994-03-25",  # score 87
    "2003-02-09",  # score 86
    "1994-02-16",  # score 86
    "1994-02-04",  # score 83
    "1994-03-04",  # score 83
    # User B (1994-11-02) matches — scores 78-99
    "1998-02-19",  # score 99
    "1999-02-14",  # score 94
    "1998-03-15",  # score 94
    "1990-04-02",  # score 91
    "1990-09-29",  # score 91
    "1991-03-28",  # score 90
    "1990-02-21",  # score 86
    "1991-03-16",  # score 82
    "1990-09-28",  # score 78
    "1990-08-21",  # score 78
]


def generate_profiles() -> list[dict[str, Any]]:
    profiles = []
    now = datetime.now(timezone.utc).isoformat()

    # Gender distribution: ~65 female, ~65 male, ~20 non-binary
    gender_pool = (
        [("female", FEMALE_NAMES)] * 65
        + [("male", MALE_NAMES)] * 65
        + [("non-binary", NB_NAMES)] * 20
    )
    random.shuffle(gender_pool)

    used_names: set[str] = set()
    pinned_index = 0

    for i in range(NUM_PROFILES):
        user_id = f"{SEED_PREFIX}{uuid.uuid4().hex[:12]}"
        gender, name_pool = gender_pool[i]

        # Pick unique first + last name combo
        while True:
            first = random.choice(name_pool)
            last = random.choice(LAST_NAMES)
            full_name = f"{first} {last}"
            if full_name not in used_names:
                used_names.add(full_name)
                break

        # First 20 profiles get pinned birthdates for BaZi demo
        if pinned_index < len(PINNED_BIRTHDATES):
            birth_date = PINNED_BIRTHDATES[pinned_index]
            pinned_index += 1
        else:
            # Age 18-45 → birth year 1981-2008
            age = random.randint(18, 45)
            birth_year = 2026 - age
            birth_month = random.randint(1, 12)
            birth_day = random.randint(1, 28)  # safe for all months
            birth_date = f"{birth_year:04d}-{birth_month:02d}-{birth_day:02d}"

        # City + coordinates with small jitter
        city_name, base_lat, base_lng = random.choice(BAY_AREA_CITIES)
        lat = round(base_lat + random.uniform(-0.02, 0.02), 4)
        lng = round(base_lng + random.uniform(-0.02, 0.02), 4)

        # Interested in
        interested_options = ["male", "female", "everyone"]
        interested_in = random.choice(interested_options)

        # Bio
        bio = generate_bio(city_name)

        # Interests (3-6 random)
        interests = random.sample(INTERESTS_POOL, random.randint(3, 6))

        # Avatar
        avatar_url = f"https://i.pravatar.cc/400?u={user_id}"

        profile = {
            "userId": user_id,
            "name": full_name,
            "gender": gender,
            "interestedIn": interested_in,
            "birthDate": birth_date,
            "location": [lat, lng],
            "city": city_name,
            "bio": bio,
            "interests": interests,
            "avatarUrl": avatar_url,
            "createdAt": now,
            "updatedAt": now,
        }
        profiles.append(profile)

    return profiles


def write_to_dynamodb(profiles: list[dict[str, Any]]) -> None:
    dynamodb = boto3.resource("dynamodb", region_name=REGION)
    profiles_table = dynamodb.Table(PROFILES_TABLE)
    discovery_table = dynamodb.Table(DISCOVERY_TABLE)

    print(f"\nWriting {len(profiles)} profiles to DynamoDB...")

    # Batch write to profiles table
    with profiles_table.batch_writer() as batch:
        for p in profiles:
            item = {
                "PK": f"USER#{p['userId']}",
                "SK": "PROFILE",
                **p,
            }
            # DynamoDB doesn't accept float in lists, convert location
            item["location"] = [str(coord) for coord in p["location"]]
            batch.put_item(Item=item)

    print(f"  ✅ {PROFILES_TABLE}: {len(profiles)} items written")

    # Batch write to discovery table
    from decimal import Decimal

    with discovery_table.batch_writer() as batch:
        for p in profiles:
            age = 2026 - int(p["birthDate"][:4])
            item = {
                "PK": f"PROFILE#{p['userId']}",
                "SK": "META",
                "userId": p["userId"],
                "displayName": p["name"],
                "gender": p["gender"],
                "preferredGender": p["interestedIn"],
                "location": [str(coord) for coord in p["location"]],
                "city": p["city"],
                "age": age,
                "birthDate": p["birthDate"],
                "avatarUrl": p["avatarUrl"],
                "bio": p["bio"][:500],
                "cachedAt": p["createdAt"],
            }
            batch.put_item(Item=item)

    print(f"  ✅ {DISCOVERY_TABLE}: {len(profiles)} items written")
    print(f"\nDone! {len(profiles)} seed profiles created.")


def delete_seeded_profiles() -> None:
    dynamodb = boto3.resource("dynamodb", region_name=REGION)
    profiles_table = dynamodb.Table(PROFILES_TABLE)
    discovery_table = dynamodb.Table(DISCOVERY_TABLE)

    # Scan for seed profiles
    print("Scanning for seeded profiles...")
    deleted = 0

    # Delete from profiles table
    scan = profiles_table.scan(
        FilterExpression="begins_with(PK, :prefix)",
        ExpressionAttributeValues={":prefix": f"USER#{SEED_PREFIX}"},
        ProjectionExpression="PK, SK",
    )
    with profiles_table.batch_writer() as batch:
        for item in scan.get("Items", []):
            batch.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})
            deleted += 1

    print(f"  ✅ {PROFILES_TABLE}: {deleted} items deleted")

    # Delete from discovery table
    deleted_disc = 0
    scan = discovery_table.scan(
        FilterExpression="begins_with(PK, :prefix)",
        ExpressionAttributeValues={":prefix": f"PROFILE#{SEED_PREFIX}"},
        ProjectionExpression="PK, SK",
    )
    with discovery_table.batch_writer() as batch:
        for item in scan.get("Items", []):
            batch.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})
            deleted_disc += 1

    print(f"  ✅ {DISCOVERY_TABLE}: {deleted_disc} items deleted")
    print(f"\nDone! All seed data removed.")


def main():
    parser = argparse.ArgumentParser(description="Seed fake profiles into Kismet DynamoDB")
    parser.add_argument("--execute", action="store_true", help="Actually write to DynamoDB (default: dry run)")
    parser.add_argument("--delete", action="store_true", help="Delete all seeded profiles")
    args = parser.parse_args()

    if args.delete:
        delete_seeded_profiles()
        return

    profiles = generate_profiles()

    # Print sample
    print(f"Generated {len(profiles)} profiles. Sample:\n")
    for p in profiles[:5]:
        print(f"  {p['name']:20s} | {p['gender']:10s} | {p['birthDate']} (age {2026 - int(p['birthDate'][:4]):2d}) | {p['city']:18s} | into: {p['interestedIn']}")
        print(f"  {'':20s}   bio: {p['bio'][:80]}...")
        print(f"  {'':20s}   interests: {', '.join(p['interests'])}")
        print()

    # Gender stats
    genders = {}
    for p in profiles:
        genders[p["gender"]] = genders.get(p["gender"], 0) + 1
    print(f"Gender distribution: {genders}")

    # Age stats
    ages = [2026 - int(p["birthDate"][:4]) for p in profiles]
    print(f"Age range: {min(ages)}-{max(ages)}, mean: {sum(ages)/len(ages):.1f}")

    # City stats
    cities = {}
    for p in profiles:
        cities[p["city"]] = cities.get(p["city"], 0) + 1
    top_cities = sorted(cities.items(), key=lambda x: -x[1])[:5]
    print(f"Top cities: {', '.join(f'{c}({n})' for c, n in top_cities)}")

    if args.execute:
        write_to_dynamodb(profiles)
    else:
        print(f"\n⚠️  Dry run — no data written. Use --execute to write to DynamoDB.")


if __name__ == "__main__":
    main()
