"""Customer text (tickets, reviews, chats) per theme, in English and Hinglish.

Texts are composed from opener + core + detail + closer banks, then varied by tone,
casing, typos and occasional second themes, so the classifier sees realistic variety.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from backend.app.schemas.taxonomy import TEXT_THEMES
from datagen.config import TextConfig

Bank = dict[str, dict[str, list[str]]]

CORES: dict[str, Bank] = {
    "delivery_delay": {
        "en": {
            "core": [
                "My {product} order still hasn't arrived.",
                "Where is my order? It was supposed to come {days} days ago.",
                "Tracking has not updated for {days} days.",
                "The {product} I ordered is stuck in transit with {courier}.",
                "Delivery date keeps getting pushed, now it shows {days} more days.",
                "Order shows out for delivery since yesterday but nothing came.",
                "Will my {product} arrive by the weekend? I need it for a function.",
                "Promised delivery date passed and no update from {courier}.",
                "It says delivery in {days} days to {city}, that is too long.",
            ],
            "detail": [
                "I have checked the tracking page many times.",
                "It's a gift and the date matters.",
                "The courier is not picking up calls.",
                "Other orders to {city} came on time.",
            ],
        },
        "hi": {
            "core": [
                "Mera order abhi tak nahi aaya, {days} din ho gaye.",
                "Bhai delivery kab hogi? tracking update hi nahi ho raha.",
                "{courier} wale ka koi update nahi hai, order atka hua hai.",
                "Delivery date baar baar aage badh rahi hai.",
                "{product} kab tak aayega? function ke liye chahiye tha.",
                "Out for delivery dikha raha hai kal se, par aaya kuch nahi.",
                "{city} ke liye {days} din delivery? bahut zyada hai.",
            ],
            "detail": [
                "Tracking page roz check kar raha hoon.",
                "Gift tha, time pe chahiye tha yaar.",
                "{city} mein baaki orders time pe aa gaye.",
            ],
        },
    },
    "size_fit": {
        "en": {
            "core": [
                "The size chart is missing for this {product}, how do I pick a size?",
                "Ordered {size} but it fits like two sizes smaller.",
                "No measurements given, can't decide between M and L.",
                "The {product} runs very large, fitting is completely off.",
                "Size {size} was too tight even though I always wear {size}.",
                "Is this {product} true to size? The listing doesn't say.",
                "Shoe size chart is in US sizes but I use UK sizes.",
                "Length is much shorter than expected.",
            ],
            "detail": [
                "I had to return it because of the fit.",
                "Please add a proper size chart.",
                "Reviews also say sizing is inconsistent.",
            ],
        },
        "hi": {
            "core": [
                "Size chart hi nahi hai, kaise pata chalega {size} lu ya bada?",
                "{size} order kiya tha par bahut tight hai.",
                "Fitting bilkul galat hai, size chota nikla.",
                "Is {product} ka size sahi hai kya? kuch likha hi nahi.",
                "Measurements daal do yaar, confuse ho raha hoon.",
            ],
            "detail": [
                "Wapas karna padega ab.",
                "Reviews mein bhi size ka issue bola hai.",
            ],
        },
    },
    "payment_trust": {
        "en": {
            "core": [
                "Payment keeps failing on {method}, is it safe to try again?",
                "I'm scared to pay again, last time money got stuck.",
                "{method} payment failed twice, will I be charged twice?",
                "Is card payment secure on your site? It keeps timing out.",
                "The payment page looks broken, not sure if it's safe.",
                "Tried {method} three times, every time it fails.",
                "Why does my payment fail only on your app?",
            ],
            "detail": [
                "I don't want to lose money.",
                "Other apps work fine with the same account.",
                "Please confirm before I try again.",
            ],
        },
        "hi": {
            "core": [
                "{method} se payment baar baar fail ho raha hai, safe hai kya?",
                "Paisa katne ka darr hai, pichli baar atak gaya tha.",
                "Do baar payment fail hua, double charge toh nahi hoga?",
                "Card se pay karne mein dikkat aa rahi hai.",
                "Payment page pe hi atak jaata hai.",
            ],
            "detail": [
                "Dusri apps pe same account chal raha hai.",
                "Pehle confirm karo phir try karunga.",
            ],
        },
    },
    "money_deducted": {
        "en": {
            "core": [
                "Money deducted {amount} but order not placed.",
                "{amount} was debited from my account and I got no order confirmation.",
                "Amount got cut via {method} but the app says payment failed.",
                "I was charged {amount} and there is no order. When will I get a refund?",
                "Payment failed but my bank shows {amount} debited.",
                "Double debit of {amount} for one attempt.",
            ],
            "detail": [
                "Please refund immediately.",
                "My bank says the money reached you.",
                "It has been {days} days already.",
            ],
        },
        "hi": {
            "core": [
                "Paise kat gaye {amount} lekin order place nahi hua.",
                "Account se {amount} debit ho gaya par order confirm nahi hua.",
                "{method} se paisa cut gaya, app bol raha hai failed.",
                "{amount} gaya aur order bhi nahi mila, refund kab aayega?",
            ],
            "detail": [
                "Jaldi refund karo please.",
                "{days} din ho gaye already.",
            ],
        },
    },
    "missing_info": {
        "en": {
            "core": [
                "The listing for {product} doesn't mention the material.",
                "No details about battery life or warranty.",
                "What is the exact capacity? It's not written anywhere.",
                "The product description is just one line, need more details.",
                "Are the specs for {product} correct? Photos show something different.",
                "Not clear if this is compatible with my phone.",
                "Only one blurry photo, can't tell the colour.",
                "The item I received was not as described in the listing.",
            ],
            "detail": [
                "I had to check three other sites for the details.",
                "Please update the product page.",
                "Compared it with two other products and it's still unclear.",
            ],
        },
        "hi": {
            "core": [
                "{product} ka material kya hai? kuch likha hi nahi.",
                "Specs mein battery backup mention hi nahi hai.",
                "Description bahut chhota hai, details do.",
                "Photo aur actual product alag hai.",
                "Ye mere phone ke saath chalega ya nahi, clear nahi hai.",
            ],
            "detail": [
                "Doosri sites pe check karna pada.",
                "Product page update karo.",
            ],
        },
    },
    "return_refund": {
        "en": {
            "core": [
                "Return pickup has been pending for {days} days.",
                "Refund of {amount} not received yet.",
                "I returned the {product} but the refund is still processing.",
                "The product arrived damaged, I want to return it.",
                "My return request got rejected without any reason.",
                "Quality is very poor, I want my money back.",
                "Refund status shows pending for {days} days.",
            ],
            "detail": [
                "Nobody from support has replied.",
                "This is my second request.",
                "Please process it quickly.",
            ],
        },
        "hi": {
            "core": [
                "Return pickup {days} din se pending hai.",
                "Refund abhi tak nahi aaya {amount} ka.",
                "Product toota hua aaya, return karna hai.",
                "Quality bekaar hai, paise wapas chahiye.",
                "Refund status {days} din se pending dikha raha hai.",
            ],
            "detail": [
                "Support se koi reply nahi aaya.",
                "Doosri baar bol raha hoon.",
            ],
        },
    },
    "login_issue": {
        "en": {
            "core": [
                "OTP is not coming, I tried resend three times.",
                "Why do I need to log in just to checkout?",
                "OTP expired before it even arrived.",
                "Login keeps failing with invalid OTP.",
                "I can't log in to track my order.",
                "Not getting the OTP by SMS, can I use email instead?",
            ],
            "detail": [
                "My cart is full and I can't proceed.",
                "Please allow guest checkout.",
                "Tried on both the app and the website.",
            ],
        },
        "hi": {
            "core": [
                "OTP aa hi nahi raha, 3 baar resend kiya.",
                "Checkout ke liye login kyun zaroori hai?",
                "OTP invalid bol raha hai baar baar.",
                "Order track karne ke liye login nahi ho raha.",
                "SMS pe OTP nahi aata, email pe bhej do.",
            ],
            "detail": [
                "Cart ready hai par aage nahi badh pa raha.",
                "Guest checkout do yaar.",
            ],
        },
    },
    "stock": {
        "en": {
            "core": [
                "My size {size} is always out of stock.",
                "I clicked notify me weeks ago, still no update.",
                "The item went out of stock while it was in my cart.",
                "Why show products that are not available?",
                "Only XS and XXL left, no normal sizes.",
                "Will the {product} be restocked?",
            ],
            "detail": [
                "I was ready to buy.",
                "The suggestions were also out of stock.",
            ],
        },
        "hi": {
            "core": [
                "Mera size {size} hamesha out of stock rehta hai.",
                "Notify me dabaya tha, kab aayega wapas?",
                "Cart mein tha aur out of stock ho gaya.",
                "Jo available nahi hai woh dikhate kyun ho?",
            ],
            "detail": ["Main kharidne ke liye ready tha."],
        },
    },
    "price_fees": {
        "en": {
            "core": [
                "Why did the total jump at checkout? Extra charges were not shown before.",
                "A delivery fee of {fee} was added at the last step.",
                "COD charges are too high.",
                "Coupon {code} is not working, it says expired.",
                "Coupon {code} says minimum cart value not met but my cart is enough.",
                "Platform fee and shipping make it costlier than other sites.",
                "The price on the product page is different from checkout.",
            ],
            "detail": [
                "Felt like hidden charges.",
                "I removed the items after seeing the total.",
                "Other sites show all charges upfront.",
            ],
        },
        "hi": {
            "core": [
                "Checkout pe itne charges kyun add ho gaye? pehle nahi dikhaya.",
                "Delivery charge {fee} last mein add kar diya.",
                "Coupon {code} apply hi nahi ho raha, expired bol raha hai.",
                "COD charge bahut zyada hai.",
                "Product page pe price alag aur checkout pe alag.",
            ],
            "detail": [
                "Hidden charges jaisa laga.",
                "Total dekh ke cart khaali kar diya.",
            ],
        },
    },
    "app_bug": {
        "en": {
            "core": [
                "The app keeps crashing on the payment page.",
                "Buttons don't respond when I tap continue.",
                "Pages take forever to load.",
                "Got an error screen while placing the order.",
                "Clicked place order many times, nothing happened.",
                "The size selector doesn't work.",
                "The tracking page shows a blank screen.",
            ],
            "detail": [
                "I'm using the latest app version.",
                "Tried reinstalling, same issue.",
                "Happens only on Android.",
            ],
        },
        "hi": {
            "core": [
                "App baar baar crash ho raha hai payment page pe.",
                "Button dabane pe kuch hota hi nahi.",
                "Page load hone mein bahut time lag raha hai.",
                "Order place karte time error aa gaya.",
                "Tracking page khaali dikh raha hai.",
            ],
            "detail": [
                "Latest version hai phir bhi.",
                "Reinstall kiya, same problem.",
            ],
        },
    },
    "other": {
        "en": {
            "core": [
                "Recommendations are irrelevant, showing things I never look at.",
                "Search doesn't find what I type.",
                "Similar products shown are all out of my budget.",
                "I searched for {product} and got random results.",
                "Suggestions keep showing items I already bought.",
            ],
            "detail": ["Had to scroll a lot.", "Makes shopping slow."],
        },
        "hi": {
            "core": [
                "Recommendations bekaar hai, kuch bhi dikha rahe ho.",
                "Jo search kiya woh mila hi nahi.",
                "Search mein random cheezein aa rahi hai.",
            ],
            "detail": ["Bahut scroll karna pada."],
        },
    },
}

NEUTRAL_QUERIES = {
    "en": [
        "Need a GST invoice for my order.",
        "Can I get this gift wrapped?",
        "Do you deliver on Sundays?",
        "How do I change my saved payment method?",
        "Is there an exchange option instead of a return?",
        "Can I add one more item to my order?",
    ],
    "hi": ["Invoice chahiye order ka.", "Gift wrap ho sakta hai kya?", "Sunday ko delivery hoti hai?"],
}

POSITIVE_REVIEWS = {
    "en": [
        "Great quality {product}, fits perfectly.",
        "Value for money, delivery was fast.",
        "Exactly as shown in the pictures.",
        "Very comfortable, would buy again.",
        "Good product, packaging was neat.",
        "Loved the colour, true to size.",
        "Works as described, battery lasts long.",
        "Arrived a day early, happy with it.",
    ],
    "hi": [
        "Bahut accha product hai, paisa vasool.",
        "Quality mast hai, fitting perfect.",
        "Delivery jaldi ho gayi, khush hoon.",
        "Jaisa photo mein tha waisa hi aaya.",
    ],
}

OPENERS = {
    "en": {
        "angry": ["Worst experience.", "This is ridiculous.", "Very disappointed.", "Totally unacceptable!", "Fed up now."],
        "neutral": ["", "Hi,", "Hello,", "Order query:", "Issue:"],
        "polite": ["Hi team,", "Hello, hope you are well.", "Dear support,", "Hi, could you please help?"],
    },
    "hi": {
        "angry": ["Bakwas service.", "Kya mazaak hai ye?", "Bahut bura experience.", "Hadd ho gayi!"],
        "neutral": ["", "Hi,", "Hello,", "Bhai,"],
        "polite": ["Hi team,", "Namaste,", "Please help karo,", "Sir/Madam,"],
    },
}

CLOSERS = {
    "en": {
        "angry": ["Fix this now!", "I will never order again.", "Worst app ever.", "Escalate this immediately."],
        "neutral": ["", "Please check.", "Let me know.", "Thanks."],
        "polite": ["Thank you!", "Appreciate your help.", "Please help, thanks.", "Kindly look into it."],
    },
    "hi": {
        "angry": ["Jaldi solve karo!", "Dobara order nahi karunga.", "Bekaar app hai."],
        "neutral": ["", "Check karo please.", "Batao."],
        "polite": ["Thank you!", "Dhanyavaad.", "Please help kar do."],
    },
}

AGENT_REPLIES = {
    "delivery_delay": "I can see the shipment is with the courier. I have raised a priority check.",
    "size_fit": "Sorry about the fit. I have shared the measurements we have for this item.",
    "payment_trust": "Payments on our site are secure. You can also try another payment method.",
    "money_deducted": "If the amount was debited without an order, it is reversed to the source account.",
    "missing_info": "Thanks for flagging this. I have asked the product team to update the details.",
    "return_refund": "I have checked your return and escalated it to the returns team.",
    "login_issue": "Sorry for the trouble. Please wait a minute and request the OTP again.",
    "stock": "This item is currently unavailable. I can share similar items that are in stock.",
    "price_fees": "All charges are listed on the order summary. Let me explain the breakdown.",
    "app_bug": "Sorry about that. I have reported this to our tech team.",
    "other": "Thanks for the feedback, I have passed it on to the team.",
}
FOLLOW_UPS = {"en": ["ok", "still waiting", "fine, thanks", "this is not helpful"], "hi": ["theek hai", "ok bhai", "abhi bhi wait kar raha hoon"]}
SHORTHAND = {"please": "pls", "you": "u", "are": "r", "because": "coz", "okay": "ok"}


@dataclass
class TextSample:
    text: str
    language: str
    theme: str
    secondary_theme: str | None
    sentiment: str
    tone: str


class _Slots(dict):
    def __missing__(self, key: str) -> str:
        return "it"


def format_amount(amount: float, rng: np.random.Generator) -> str:
    value = int(round(amount))
    styles = [f"₹{value:,}", f"Rs {value}", f"Rs. {value:,}", f"{value} rs", f"INR {value}"]
    return styles[int(rng.integers(len(styles)))]


class TextGenerator:
    def __init__(self, cfg: TextConfig, rng: np.random.Generator) -> None:
        self.cfg = cfg
        self.rng = rng

    def _pick(self, options: list[str]) -> str:
        return options[int(self.rng.integers(len(options)))]

    def _language(self) -> str:
        return "hinglish" if self.rng.random() < self.cfg.hinglish_share else "en"

    def _tone(self) -> str:
        roll = self.rng.random()
        return "angry" if roll < 0.35 else "neutral" if roll < 0.80 else "polite"

    def _typos(self, text: str, lang_key: str) -> str:
        words = text.split(" ")
        if lang_key == "en" and self.rng.random() < 0.15:
            words = [SHORTHAND.get(w.lower(), w) for w in words]
        if self.rng.random() < self.cfg.typo_rate:
            idx = int(self.rng.integers(len(words)))
            w = words[idx]
            if len(w) > 3 and w.isalpha():
                j = int(self.rng.integers(len(w) - 1))
                words[idx] = w[:j] + w[j + 1] + w[j] + w[j + 2:]
        return " ".join(words)

    def _fill(self, template: str, slots: dict[str, Any]) -> str:
        return template.format_map(_Slots({k: v for k, v in slots.items() if v is not None}))

    def complaint(self, theme: str, slots: dict[str, Any], tone: str | None = None) -> TextSample:
        assert theme in TEXT_THEMES, theme
        language = self._language()
        key = "hi" if language == "hinglish" else "en"
        tone = tone or self._tone()
        bank = CORES[theme][key]
        parts = [self._pick(OPENERS[key][tone]), self._pick(bank["core"])]
        if self.rng.random() < 0.5:
            parts.append(self._pick(bank["detail"]))

        secondary = None
        if self.rng.random() < self.cfg.multi_theme_rate:
            others = [t for t in TEXT_THEMES if t not in (theme, "other")]
            secondary = self._pick(others)
            extra = self._pick(CORES[secondary][key]["core"])
            parts.append(("Also, " if key == "en" else "Aur ") + extra[0].lower() + extra[1:])

        if self.rng.random() < 0.6:
            parts.append(self._pick(CLOSERS[key][tone]))
        text = " ".join(p for p in parts if p)
        text = self._typos(self._fill(text, slots), key)
        if tone == "angry" and self.rng.random() < 0.2:
            text = text.upper()
        elif self.rng.random() < 0.15:
            text = text.lower()
        return TextSample(text, language, theme, secondary, "negative", tone)

    def neutral_query(self, slots: dict[str, Any]) -> TextSample:
        language = self._language()
        key = "hi" if language == "hinglish" else "en"
        text = self._typos(self._fill(self._pick(NEUTRAL_QUERIES[key]), slots), key)
        return TextSample(text, language, "other", None, "neutral", "neutral")

    def positive_review(self, slots: dict[str, Any]) -> TextSample:
        language = self._language()
        key = "hi" if language == "hinglish" else "en"
        text = self._typos(self._fill(self._pick(POSITIVE_REVIEWS[key]), slots), key)
        return TextSample(text, language, "other", None, "positive", "polite")

    def chat_turns(self, sample: TextSample) -> list[dict[str, str]]:
        key = "hi" if sample.language == "hinglish" else "en"
        turns = [
            {"role": "agent", "text": "Hi! How can I help you today?"},
            {"role": "customer", "text": sample.text},
            {"role": "agent", "text": AGENT_REPLIES[sample.theme]},
        ]
        if self.rng.random() < 0.6:
            turns.append({"role": "customer", "text": self._pick(FOLLOW_UPS[key])})
        turns.append({"role": "agent", "text": "Is there anything else I can help with?"})
        return turns
