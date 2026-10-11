"""Launch plan templates: what each kind of business needs before it opens.

A template keeps the checklist complete (a model asked from scratch forgets
whole categories, like deposits or the licences) and gives every item a rough
price range in rupees, shown as "Hangul's estimate" until sourcing finds real
sellers. The ranges are deliberately wide: they are a starting point the user
edits, not a quote. India only for now (licences and suppliers differ by
country).

Quantities and some prices depend on the size the user picks:
``home`` (from home, a cart or a tiny space), ``small`` (one small unit) and
``large`` (a bigger place with staff).
"""

from dataclasses import asdict, dataclass, field

SIZES = ("home", "small", "large")
RENTING = ("yes", "own", "no")          # renting a place / own or family space / no place needed
CATEGORIES = {
    "equipment": "Equipment",
    "space": "Space and fit-out",
    "licence": "Licences and registration",
    "stock": "Opening stock",
    "software": "Software and online",
    "marketing": "Launch marketing",
    "staff": "Staff (monthly)",
    "running": "Running costs (monthly)",
}
TEMPLATES_VERSION = 1


@dataclass(frozen=True)
class Item:
    key: str
    name: str
    category: str                 # CATEGORIES
    low: int                      # rupees per unit, Hangul's estimate
    high: int
    qty: tuple[int, int, int] = (1, 1, 1)      # by size: home, small, large (0 = not needed)
    monthly: bool = False         # a monthly cost, not a one-off
    search: str = ""              # web search for sellers and prices ("" = not sourced: fees, salaries)
    local: str = ""               # map search for nearby suppliers ("" = none)
    needs_rent: bool = False      # only when renting a place
    by_size: dict[str, tuple[int, int]] | None = None   # price range that changes with size (rent)
    why: str = ""

    def range_for(self, size: str) -> tuple[int, int]:
        return (self.by_size or {}).get(size, (self.low, self.high))

    def qty_for(self, size: str) -> int:
        return self.qty[SIZES.index(size)] if size in SIZES else self.qty[1]


@dataclass(frozen=True)
class Variable:
    """A cost that grows with every sale, as a share of the price."""
    key: str
    label: str
    pct: float                    # 0.30 = 30% of the selling price


@dataclass(frozen=True)
class Benchmark:
    key: str
    label: str
    query: str                    # web search
    typical: str                  # Hangul's estimate when no source is found, e.g. "28-35%"


@dataclass(frozen=True)
class Kind:
    key: str
    label: str
    blurb: str
    unit: str                     # what one sale is: "order", "bill", "visit"
    price: int                    # average rupees per sale
    units_per_day: tuple[int, int, int]        # by size
    days_per_month: int
    variable: tuple[Variable, ...]
    items: tuple[Item, ...]
    benchmarks: tuple[Benchmark, ...]
    size_labels: tuple[str, str, str]
    keywords: tuple[str, ...] = field(default=())

    def as_dict(self) -> dict:
        d = asdict(self)
        d["sizes"] = [{"key": k, "label": v} for k, v in zip(SIZES, self.size_labels)]
        return d


def _fssai(level_small=(100, 3000)) -> Item:
    return Item("fssai", "FSSAI food licence (registration or state licence)", "licence", *level_small,
                why="Anyone who makes or sells food needs it; basic registration for small turnovers, a state licence above that.")


def _common_licences() -> tuple[Item, ...]:
    return (
        Item("gst", "GST registration", "licence", 0, 3000,
             why="Free on the GST portal; the range is a CA's fee. Needed above the turnover limit, for selling "
                 "online across states, and to work with most aggregators."),
        Item("shop_act", "Shops & Establishments registration", "licence", 500, 5000, qty=(0, 1, 1),
             why="State labour department registration for a shop or office with a place of business."),
        Item("trade", "Trade licence (municipal)", "licence", 1000, 10000, qty=(0, 1, 1),
             why="From the city corporation or municipality; the fee depends on the area and trade."),
        Item("ca", "CA / registration help", "licence", 2000, 15000,
             why="Optional: someone to file the registrations and set up GST returns."),
    )


CLOUD_KITCHEN = Kind(
    key="cloud_kitchen", label="Cloud kitchen", unit="order", price=300, days_per_month=30,
    blurb="A delivery-only kitchen selling through Swiggy, Zomato and your own orders.",
    units_per_day=(15, 40, 100),
    size_labels=("From my home kitchen", "One small kitchen", "Bigger kitchen, 2+ brands"),
    keywords=("cloud kitchen", "delivery kitchen", "tiffin", "home kitchen", "dark kitchen", "food delivery",
              "biryani", "meal", "meals", "catering"),
    variable=(Variable("food", "Ingredients (food cost)", 0.32), Variable("packaging", "Packaging", 0.06),
              Variable("commission", "Aggregator commission", 0.25)),
    items=(
        Item("burner", "Commercial gas range (3-4 burner)", "equipment", 15000, 45000, qty=(0, 1, 2),
             search="commercial 3 burner gas range price", local="commercial kitchen equipment"),
        Item("fridge", "Commercial refrigerator / deep freezer", "equipment", 25000, 80000, qty=(0, 1, 2),
             search="commercial deep freezer 300 litre price", local="commercial kitchen equipment"),
        Item("exhaust", "Exhaust hood and chimney", "equipment", 20000, 60000, qty=(0, 1, 1),
             search="commercial kitchen exhaust hood price"),
        Item("tables", "Stainless steel work tables", "equipment", 8000, 20000, qty=(0, 2, 4),
             search="stainless steel kitchen work table price"),
        Item("cookware", "Utensils and cookware", "equipment", 15000, 60000, qty=(1, 1, 2),
             search="commercial kitchen utensils set price"),
        Item("sealer", "Packaging sealing machine", "equipment", 5000, 15000,
             search="food container sealing machine price"),
        Item("extinguisher", "Fire extinguishers", "equipment", 1500, 4000, qty=(1, 2, 4),
             search="ABC fire extinguisher 4 kg price"),
        Item("purifier", "Commercial water purifier", "equipment", 10000, 30000, qty=(0, 1, 1),
             search="commercial RO water purifier 25 LPH price"),
        Item("fitout", "Kitchen fit-out (plumbing, gas line, tiling)", "space", 50000, 200000, qty=(0, 1, 2),
             needs_rent=True),
        Item("deposit", "Rent deposit", "space", 45000, 150000, needs_rent=True,
             by_size={"small": (45000, 150000), "large": (100000, 300000)},
             why="Usually 3-6 months' rent, returned when you leave."),
        _fssai(),
        *_common_licences(),
        Item("fire_noc", "Fire NOC", "licence", 2000, 15000, qty=(0, 0, 1),
             why="Needed for larger kitchens in most cities; check with the local fire department."),
        Item("listing", "Swiggy / Zomato onboarding", "software", 0, 10000,
             why="Onboarding fees vary by city and offer; ask both platforms' partner teams."),
        Item("pos", "Billing / POS software", "software", 500, 2000, monthly=True,
             search="restaurant POS software monthly price India"),
        Item("photos", "Menu photos", "marketing", 3000, 15000,
             search="food photography for restaurant menu price"),
        Item("launch_ads", "Launch offers and in-app ads", "marketing", 5000, 30000),
        Item("cook", "Cook", "staff", 15000, 30000, qty=(0, 1, 3), monthly=True),
        Item("helper", "Kitchen helper", "staff", 9000, 15000, qty=(0, 1, 3), monthly=True),
        Item("rent", "Rent", "running", 15000, 40000, monthly=True, needs_rent=True,
             by_size={"small": (15000, 40000), "large": (35000, 90000)}),
        Item("utilities", "Gas, electricity and water", "running", 4000, 20000, monthly=True,
             by_size={"home": (2000, 6000), "small": (8000, 20000), "large": (20000, 50000)}),
        Item("marketing", "Monthly ads and offers", "running", 3000, 20000, monthly=True),
    ),
    benchmarks=(
        Benchmark("food_cost", "Food cost as % of sales", "cloud kitchen food cost percentage India", "28-35%"),
        Benchmark("commission", "Aggregator commission", "Swiggy Zomato commission percentage restaurants", "18-30%"),
        Benchmark("aov", "Average order value", "cloud kitchen average order value India", "₹250-400"),
        Benchmark("orders", "Orders per day for a new cloud kitchen", "new cloud kitchen orders per day India", "20-60"),
    ),
)

CAFE = Kind(
    key="cafe", label="Café", unit="bill", price=320, days_per_month=30,
    blurb="A coffee shop or small café with seating.",
    units_per_day=(25, 45, 110),
    size_labels=("A kiosk or cart", "A small café (15-25 seats)", "A bigger café (40+ seats)"),
    keywords=("cafe", "café", "coffee", "coffee shop", "tea", "chai", "bakery", "kiosk", "tea stall"),
    variable=(Variable("cogs", "Ingredients (food and drink cost)", 0.30), Variable("consumables", "Cups, packaging, napkins", 0.05),
              Variable("wastage", "Wastage", 0.03), Variable("payments", "Card / UPI fees", 0.01)),
    items=(
        Item("espresso", "Espresso machine", "equipment", 80000, 300000,
             search="commercial espresso machine 1 group price India", local="coffee machine dealer"),
        Item("grinder", "Coffee grinder", "equipment", 25000, 90000,
             search="commercial coffee grinder price India", local="coffee machine dealer"),
        Item("fridge", "Under-counter refrigerator", "equipment", 25000, 70000, qty=(1, 1, 2),
             search="under counter refrigerator commercial price"),
        Item("display", "Display counter (chilled)", "equipment", 40000, 120000, qty=(0, 1, 1),
             search="cake display counter chiller price"),
        Item("oven", "Oven / microwave", "equipment", 10000, 60000,
             search="commercial convection oven price"),
        Item("blender", "Blender", "equipment", 8000, 35000,
             search="commercial blender price India"),
        Item("smallwares", "Cups, glasses, crockery and tools", "equipment", 15000, 60000, qty=(1, 1, 2)),
        Item("furniture", "Tables and chairs", "space", 60000, 250000, qty=(0, 1, 2),
             search="cafe tables and chairs set price", local="furniture shop"),
        Item("interiors", "Interiors, lighting and signage", "space", 150000, 800000, qty=(0, 1, 1),
             by_size={"home": (30000, 100000), "small": (150000, 600000), "large": (500000, 1500000)}),
        Item("cart", "Kiosk or cart build", "space", 50000, 200000, qty=(1, 0, 0),
             search="coffee kiosk cart fabrication price"),
        Item("ac", "Air conditioner", "equipment", 35000, 60000, qty=(0, 1, 3),
             search="1.5 ton split AC price"),
        Item("deposit", "Rent deposit", "space", 60000, 300000, needs_rent=True,
             by_size={"home": (10000, 40000), "small": (60000, 300000), "large": (200000, 800000)},
             why="Usually 3-10 months' rent for shop space."),
        _fssai(),
        *_common_licences(),
        Item("eating_house", "Eating house licence (police, some cities)", "licence", 0, 10000, qty=(0, 1, 1)),
        Item("music", "Music licence (if you play music)", "licence", 0, 30000, qty=(0, 1, 1),
             why="Playing recorded music in public needs a licence (e.g. PPL / IPRS / Novex), depending on the music."),
        Item("fire_noc", "Fire NOC", "licence", 2000, 15000, qty=(0, 0, 1)),
        Item("pos", "Billing / POS software", "software", 500, 2000, monthly=True,
             search="cafe POS software monthly price India"),
        Item("launch", "Launch marketing (signage, flyers, opening offer)", "marketing", 10000, 50000),
        Item("barista", "Barista", "staff", 14000, 25000, qty=(1, 2, 4), monthly=True),
        Item("server", "Server / cleaner", "staff", 9000, 15000, qty=(0, 1, 3), monthly=True),
        Item("kitchen", "Cook / kitchen helper", "staff", 12000, 22000, qty=(0, 1, 2), monthly=True),
        Item("upkeep", "Maintenance and repairs", "running", 3000, 10000, monthly=True),
        Item("rent", "Rent", "running", 25000, 80000, monthly=True, needs_rent=True,
             by_size={"home": (5000, 15000), "small": (25000, 80000), "large": (80000, 250000)}),
        Item("utilities", "Electricity, water and gas", "running", 8000, 25000, monthly=True,
             by_size={"home": (2000, 6000), "small": (8000, 25000), "large": (25000, 60000)}),
        Item("beans", "Coffee beans and supplies kept in stock", "stock", 10000, 40000),
        Item("marketing", "Monthly marketing", "running", 3000, 20000, monthly=True),
    ),
    benchmarks=(
        Benchmark("cogs", "Food and drink cost as % of sales", "cafe food cost percentage India", "25-35%"),
        Benchmark("rent_share", "Rent as % of revenue", "restaurant rent percentage of revenue India", "10-15%"),
        Benchmark("ticket", "Average bill per customer", "average bill value cafe India", "₹250-500"),
        Benchmark("payback", "Typical payback period for a café", "cafe payback period India", "18-36 months"),
    ),
)

RETAIL = Kind(
    key="retail_shop", label="Retail shop", unit="bill", price=600, days_per_month=28,
    blurb="A shop selling goods: a kirana, clothing, stationery, gifts, mobile accessories…",
    units_per_day=(12, 35, 100),
    size_labels=("From home or a stall", "A small shop", "A bigger store"),
    keywords=("shop", "store", "kirana", "grocery", "boutique", "clothing store", "garments", "stationery",
              "gift shop", "mobile shop", "retail", "supermarket", "medical store", "pharmacy"),
    variable=(Variable("cogs", "Cost of the goods sold", 0.75), Variable("payments", "Card / UPI fees", 0.01),
              Variable("bags", "Bags and wrapping", 0.01), Variable("shrinkage", "Damaged, expired or lost stock", 0.02)),
    items=(
        Item("racks", "Shelving and racks", "space", 30000, 150000, qty=(0, 1, 2),
             search="shop display racks price", local="shop racks"),
        Item("counter", "Billing counter", "space", 15000, 50000, qty=(0, 1, 2),
             search="shop billing counter price"),
        Item("pos", "POS machine, barcode scanner and printer", "equipment", 15000, 45000, qty=(0, 1, 2),
             search="billing machine with barcode scanner printer price India"),
        Item("cctv", "CCTV cameras", "equipment", 10000, 30000, qty=(0, 1, 1),
             search="4 camera CCTV kit price India", local="CCTV shop"),
        Item("signage", "Signboard", "space", 8000, 50000, qty=(0, 1, 1), search="shop sign board price"),
        Item("interiors", "Interiors and lighting", "space", 50000, 300000, qty=(0, 1, 1),
             by_size={"small": (50000, 300000), "large": (300000, 1200000)}),
        Item("ac", "Air conditioner", "equipment", 35000, 60000, qty=(0, 1, 2), search="1.5 ton split AC price"),
        Item("stock", "Opening stock", "stock", 100000, 500000,
             by_size={"home": (20000, 100000), "small": (100000, 500000), "large": (500000, 2500000)},
             why="Usually the biggest start-up cost in retail: enough to fill the shelves for the first weeks."),
        Item("deposit", "Rent deposit", "space", 50000, 300000, needs_rent=True,
             by_size={"home": (10000, 30000), "small": (50000, 300000), "large": (200000, 1000000)}),
        *_common_licences(),
        Item("billing_sw", "Billing and inventory software", "software", 300, 1500, monthly=True,
             search="retail billing inventory software monthly price India"),
        Item("launch", "Opening offer and flyers", "marketing", 5000, 30000),
        Item("staff", "Sales staff", "staff", 10000, 18000, qty=(0, 1, 4), monthly=True),
        Item("rent", "Rent", "running", 15000, 60000, monthly=True, needs_rent=True,
             by_size={"home": (3000, 10000), "small": (15000, 60000), "large": (60000, 250000)}),
        Item("utilities", "Electricity and internet", "running", 3000, 12000, monthly=True,
             by_size={"home": (1000, 3000), "small": (3000, 12000), "large": (12000, 40000)}),
    ),
    benchmarks=(
        Benchmark("margin", "Gross margin in this kind of retail", "retail shop gross margin percentage India", "15-40%"),
        Benchmark("turns", "Stock turnover (times a year)", "retail inventory turnover ratio India small shop", "4-8"),
        Benchmark("rent_share", "Rent as % of sales", "retail rent as percentage of sales India", "5-10%"),
        Benchmark("bill", "Average bill value", "average bill value retail store India", "₹300-1,000"),
    ),
)

SALON = Kind(
    key="salon", label="Salon", unit="visit", price=500, days_per_month=28,
    blurb="A hair and beauty salon or barbershop.",
    units_per_day=(5, 18, 45),
    size_labels=("From home / home visits", "A small salon (2-3 chairs)", "A bigger salon (6+ chairs)"),
    keywords=("salon", "parlour", "parlor", "barber", "barbershop", "beauty", "spa", "hair", "makeup", "nail"),
    variable=(Variable("products", "Products used per visit", 0.12), Variable("payments", "Card / UPI fees", 0.01),
              Variable("incentive", "Staff incentive", 0.08)),
    items=(
        Item("chairs", "Styling chairs", "equipment", 8000, 40000, qty=(1, 3, 6),
             search="salon styling chair hydraulic price", local="salon furniture"),
        Item("stations", "Mirror stations", "equipment", 8000, 30000, qty=(0, 3, 6),
             search="salon mirror station price"),
        Item("wash", "Shampoo / wash station", "equipment", 15000, 50000, qty=(0, 1, 2),
             search="salon shampoo station price"),
        Item("tools", "Dryers, straighteners, trimmers and tools", "equipment", 15000, 60000, qty=(1, 1, 2),
             search="professional salon hair dryer straightener kit price"),
        Item("sterilizer", "UV sterilizer", "equipment", 2000, 8000, search="salon UV sterilizer price"),
        Item("pedicure", "Pedicure chair", "equipment", 20000, 80000, qty=(0, 0, 1),
             search="pedicure chair price India"),
        Item("interiors", "Interiors, lighting and signage", "space", 150000, 600000, qty=(0, 1, 1),
             by_size={"small": (150000, 600000), "large": (500000, 1500000)}),
        Item("ac", "Air conditioner", "equipment", 35000, 60000, qty=(0, 1, 2), search="1.5 ton split AC price"),
        Item("products", "Opening product stock", "stock", 15000, 100000,
             by_size={"home": (10000, 30000), "small": (30000, 100000), "large": (100000, 300000)}),
        Item("deposit", "Rent deposit", "space", 50000, 250000, needs_rent=True,
             by_size={"small": (50000, 250000), "large": (200000, 800000)}),
        *_common_licences(),
        Item("health", "Health / trade licence for salons (some cities)", "licence", 0, 10000, qty=(0, 1, 1)),
        Item("booking", "Booking and billing software", "software", 500, 2500, monthly=True,
             search="salon booking software monthly price India"),
        Item("launch", "Opening offers and local ads", "marketing", 5000, 40000),
        Item("stylist", "Stylists", "staff", 15000, 35000, qty=(0, 2, 5), monthly=True),
        Item("helper", "Helper / receptionist", "staff", 9000, 15000, qty=(0, 1, 2), monthly=True),
        Item("rent", "Rent", "running", 20000, 70000, monthly=True, needs_rent=True,
             by_size={"small": (20000, 70000), "large": (70000, 200000)}),
        Item("utilities", "Electricity and water", "running", 5000, 20000, monthly=True,
             by_size={"home": (1000, 3000), "small": (5000, 20000), "large": (20000, 50000)}),
    ),
    benchmarks=(
        Benchmark("ticket", "Average spend per visit", "salon average ticket size India", "₹400-1,200"),
        Benchmark("staff_share", "Staff cost as % of revenue", "salon staff cost percentage of revenue", "35-50%"),
        Benchmark("product_share", "Product cost as % of service revenue", "salon product cost percentage of revenue", "8-15%"),
        Benchmark("rebooking", "Repeat / rebooking rate", "salon client retention rate", "40-60%"),
    ),
)

D2C = Kind(
    key="d2c_brand", label="Online brand (D2C)", unit="order", price=800, days_per_month=30,
    blurb="Your own products sold online: your website, Instagram, Amazon or Flipkart.",
    units_per_day=(3, 15, 60),
    size_labels=("Side project from home", "Small brand, a few products", "Growing brand with a warehouse"),
    keywords=("d2c", "online brand", "online store", "ecommerce", "e-commerce", "shopify", "sell online",
              "instagram store", "amazon", "flipkart", "my own brand", "skincare brand", "clothing brand"),
    variable=(Variable("cogs", "Product cost", 0.35), Variable("shipping", "Shipping", 0.10),
              Variable("packaging", "Packaging", 0.04), Variable("gateway", "Payment gateway", 0.02),
              Variable("returns", "Returns and RTO", 0.05)),
    items=(
        Item("samples", "Product development and samples", "stock", 20000, 100000,
             search="private label manufacturer sample cost India", local=""),
        Item("stock", "First production run / inventory", "stock", 100000, 500000,
             by_size={"home": (25000, 100000), "small": (100000, 500000), "large": (500000, 2500000)},
             why="The minimum order quantity (MOQ) of your manufacturer decides this; ask several."),
        Item("packaging_design", "Packaging design", "marketing", 10000, 50000,
             search="product packaging design cost India"),
        Item("photos", "Product photography", "marketing", 8000, 50000,
             search="ecommerce product photography price per product India"),
        Item("website", "Website set-up (Shopify / WooCommerce)", "software", 10000, 60000,
             search="shopify store setup cost India"),
        Item("store_sub", "Store subscription and apps", "software", 1500, 6000, monthly=True,
             search="Shopify plan price India per month"),
        Item("trademark", "Trademark application", "licence", 4500, 15000,
             why="Government fee ₹4,500 per class for individuals and small businesses (₹9,000 otherwise), plus an "
                 "attorney's fee if you use one."),
        Item("gst", "GST registration", "licence", 0, 3000,
             why="Needed to sell on Amazon and Flipkart and to ship to other states."),
        Item("ca", "CA / registration help", "licence", 2000, 15000),
        Item("warehouse", "Warehouse or storage space", "space", 0, 40000, qty=(0, 0, 1), monthly=True, needs_rent=True),
        Item("shipping_setup", "Shipping aggregator (Shiprocket, Delhivery…)", "software", 0, 0,
             search="Shiprocket shipping rates per 500g India",
             why="No set-up fee on most plans; you pay per shipment (in the variable costs)."),
        Item("launch_ads", "Launch ads and influencer seeding", "marketing", 20000, 150000),
        Item("ads", "Monthly ads (Meta / Google)", "running", 15000, 150000, monthly=True,
             by_size={"home": (5000, 20000), "small": (15000, 150000), "large": (150000, 600000)},
             why="Usually the biggest monthly cost of an online brand."),
        Item("packer", "Packing / operations help", "staff", 10000, 15000, qty=(0, 1, 3), monthly=True),
    ),
    benchmarks=(
        Benchmark("cac", "Customer acquisition cost (CAC)", "D2C brand customer acquisition cost India", "₹300-1,000"),
        Benchmark("rto", "RTO / return rate for COD orders", "ecommerce RTO rate India COD", "20-30% of COD orders"),
        Benchmark("conversion", "Website conversion rate", "ecommerce conversion rate India", "1-3%"),
        Benchmark("gross_margin", "Gross margin of D2C brands", "D2C brand gross margin India", "55-70%"),
    ),
)

KINDS: dict[str, Kind] = {k.key: k for k in (CLOUD_KITCHEN, CAFE, RETAIL, SALON, D2C)}


def get(kind: str) -> Kind | None:
    return KINDS.get(kind)


def match_kind(text: str) -> str | None:
    """The template a sentence is about, by whole-word keywords (longest match wins)."""
    import re
    t = f" {(text or '').lower()} "
    best: tuple[int, str] | None = None
    for k in KINDS.values():
        for w in k.keywords + (k.label.lower(),):
            if re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", t) and (best is None or len(w) > best[0]):
                best = (len(w), k.key)
    return best[1] if best else None


def catalogue() -> list[dict]:
    """What the form shows: each kind with its sizes."""
    return [{"key": k.key, "label": k.label, "blurb": k.blurb, "unit": k.unit,
             "sizes": [{"key": s, "label": label} for s, label in zip(SIZES, k.size_labels)]}
            for k in KINDS.values()]
