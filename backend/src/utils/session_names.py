"""Human-readable session display names.

Format: {adjective}-{animal}
Example: swift-badger

Session IDs remain UUIDs (required by Claude SDK for JSONL file mapping).
The display_name column stores a human-readable name for UI/Telegram display.
"""

import random

# ── Adjectives (~350) ────────────────────────────────────────────────────────
# Short, positive/neutral, easy to read. Sorted alphabetically.

ADJECTIVES: tuple[str, ...] = (
    "able", "acid", "aged", "airy", "alert", "alive", "amber", "ample",
    "apt", "aqua", "arch", "arid", "avid", "azure",
    "bare", "base", "bold", "bone", "brave", "brief", "bright", "brisk",
    "broad", "bronze", "brown", "burly",
    "calm", "cedar", "chief", "chill", "civic", "civil", "clean", "clear",
    "clever", "close", "coal", "coarse", "cobalt", "cold", "cool", "coral",
    "core", "cozy", "crisp", "cubic", "curly", "cyan",
    "daily", "dark", "dawn", "dear", "deep", "delta", "dense", "dewy",
    "dim", "dire", "dry", "dual", "dull", "dusk", "dusty",
    "eager", "early", "east", "easy", "edgy", "elfin", "elite", "elm",
    "epic", "equal", "even", "exact", "extra",
    "faint", "fair", "far", "fast", "fawn", "fierce", "fine", "firm",
    "first", "fit", "flat", "fleet", "flint", "flora", "fluid", "focal",
    "fond", "fore", "forge", "formal", "forte", "fossil", "frank", "free",
    "fresh", "front", "frost", "full", "fused",
    "gale", "game", "glad", "glass", "gleam", "global", "gold", "good",
    "grace", "grand", "gray", "green", "grey", "grim", "grit",
    "half", "hale", "happy", "hard", "hardy", "hazel", "heavy", "hex",
    "high", "hollow", "honey", "hot", "huge", "humble",
    "icy", "idle", "inner", "iron", "ivory",
    "jade", "jet", "jolly", "just",
    "keen", "kept", "kind", "knit",
    "lame", "large", "laser", "last", "late", "lead", "lean", "level",
    "light", "lilac", "lime", "lithe", "live", "local", "lone", "long",
    "lost", "loud", "low", "loyal", "lucid", "lunar",
    "macro", "maize", "major", "maple", "marsh", "mass", "matte", "meek",
    "merry", "micro", "mild", "mint", "modal", "moist", "moral", "mossy",
    "mute",
    "naive", "narrow", "natal", "naval", "near", "neat", "new", "next",
    "nimble", "noble", "north", "novel", "numb",
    "oaken", "odd", "olive", "only", "opal", "open", "other", "outer",
    "oval",
    "pale", "palm", "peak", "pearl", "penny", "pine", "pink", "pixel",
    "plain", "plum", "plush", "polar", "polite", "pond", "prime", "prior",
    "proud", "pure",
    "quick", "quiet", "quill",
    "rapid", "rare", "raw", "real", "red", "reef", "regal", "rich",
    "rigid", "ripe", "rival", "river", "roast", "rocky", "roman", "root",
    "rose", "rough", "round", "royal", "ruby", "rural", "rusty",
    "safe", "sage", "salt", "same", "sandy", "satin", "sharp", "sheer",
    "short", "shy", "silk", "silver", "simple", "slim", "slow", "small",
    "smart", "smoke", "smooth", "snowy", "soft", "solar", "sole", "solid",
    "sonic", "south", "spare", "spicy", "split", "stale", "stark", "steady",
    "steel", "steep", "stern", "still", "stone", "storm", "stout", "strict",
    "strong", "subtle", "sugar", "sunny", "super", "sure", "sweet", "swift",
    "tall", "tame", "tan", "tart", "teal", "tender", "thick", "thin",
    "third", "thorn", "tidal", "tidy", "tight", "timber", "tiny", "token",
    "topaz", "total", "tough", "trim", "true", "tulip", "twin",
    "ultra", "uncut", "upper", "urban",
    "valid", "vast", "velvet", "vivid", "vocal", "void",
    "warm", "wary", "wavy", "west", "wheat", "white", "whole", "wide",
    "wild", "wise", "worn",
    "young",
    "zeal", "zero", "zinc",
)

# ── Animals (~350) ───────────────────────────────────────────────────────────
# Short, recognizable, distinct. Sorted alphabetically.

ANIMALS: tuple[str, ...] = (
    "adder", "albatross", "alligator", "alpaca", "anchovy", "ant", "ape",
    "asp", "auk", "axolotl",
    "baboon", "badger", "barb", "bass", "bat", "bear", "beaver", "bee",
    "beetle", "bison", "boa", "boar", "bobcat", "bongo", "bonito",
    "booby", "buck", "buffalo", "bull", "bunny", "burro", "buzzard",
    "camel", "canary", "capybara", "caracal", "carp", "cat", "catfish",
    "cheetah", "chicken", "chimp", "chinchilla", "chipmunk", "cicada",
    "clam", "cobra", "cockatoo", "cod", "colt", "condor", "coral",
    "cougar", "cow", "coyote", "crab", "crane", "crayfish", "cricket",
    "crow", "cuckoo", "curlew",
    "dace", "darter", "deer", "dingo", "dog", "dolphin", "donkey", "dove",
    "dragon", "drake", "drum", "duck", "dugong", "dunlin",
    "eagle", "eel", "egret", "elk", "emu",
    "falcon", "ferret", "finch", "firefly", "fish", "flamingo", "flea",
    "flounder", "fly", "fox", "frog",
    "gannet", "gar", "gazelle", "gecko", "gerbil", "gibbon", "gnat",
    "gnu", "goat", "goose", "gopher", "gorilla", "grackle", "grouse",
    "grub", "gull", "guppy",
    "haddock", "hamster", "hare", "harrier", "hawk", "hedgehog", "hen",
    "heron", "herring", "hippo", "hornet", "horse", "hound", "hummingbird",
    "hyena",
    "ibex", "ibis", "iguana", "impala",
    "jackal", "jackdaw", "jaguar", "jay", "jellyfish",
    "kangaroo", "kestrel", "kingfish", "kite", "kitten", "kiwi", "koala",
    "koi", "krill",
    "lark", "lemming", "lemur", "leopard", "limpet", "lion", "lizard",
    "llama", "lobster", "locust", "loon", "loris", "louse", "lynx",
    "macaw", "mackerel", "magpie", "mallard", "mamba", "manatee",
    "mandrill", "mantis", "marlin", "marmot", "marten", "martin",
    "mayfly", "meerkat", "mink", "minnow", "mole", "mongoose", "monkey",
    "moose", "moth", "mouse", "mule", "mullet", "mussel",
    "narwhal", "newt", "nuthatch",
    "ocelot", "octopus", "okapi", "opossum", "orca", "oriole", "oryx",
    "osprey", "ostrich", "otter", "owl", "ox", "oyster",
    "panda", "panther", "parrot", "partridge", "peacock", "pelican",
    "penguin", "perch", "petrel", "pheasant", "pig", "pigeon", "pike",
    "piranha", "plover", "polecat", "pollock", "pony", "poodle",
    "porcupine", "porpoise", "possum", "prawn", "puffin", "puma",
    "python",
    "quail", "quetzal", "quokka",
    "rabbit", "raccoon", "ram", "rat", "rattler", "raven", "ray",
    "reindeer", "rhino", "robin", "rooster", "rook",
    "sailfish", "salamander", "salmon", "sandpiper", "sardine", "sawfish",
    "scorpion", "seahorse", "seal", "shark", "sheep", "shrew", "shrimp",
    "skate", "skink", "skunk", "sloth", "slug", "smelt", "snail", "snake",
    "snipe", "sole", "sparrow", "spider", "squid", "squirrel", "stag",
    "starling", "stingray", "stork", "sturgeon", "sunfish", "swallow",
    "swan", "swift",
    "tapir", "tarpon", "teal", "termite", "tern", "thrush", "tiger",
    "toad", "tortoise", "toucan", "trout", "tuna", "turkey", "turtle",
    "viper", "vole", "vulture",
    "walrus", "warthog", "wasp", "weasel", "whale", "whimbrel", "wolf",
    "wombat", "woodcock", "worm", "wren",
    "yak",
    "zebra",
)


def generate_display_name() -> str:
    """Generate a human-readable display name like 'swift-badger'."""
    return f"{random.choice(ADJECTIVES)}-{random.choice(ANIMALS)}"


def short_name(session_id: str, display_name: str | None = None) -> str:
    """Return the best short label for a session.

    Uses display_name if available, otherwise falls back to first 8 chars
    of the session_id (legacy UUIDs).
    """
    if display_name:
        return display_name
    return session_id[:8]
