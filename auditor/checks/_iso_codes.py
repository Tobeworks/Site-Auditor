"""ISO-639-1 language codes and a common subset of ISO-3166-1 alpha-2 country
codes, used to validate hreflang values in social.py.

ISO_639_1 is the complete 184-code set. ISO_3166_1 covers the ~90 most
common country codes, not the full 249 — extend as needed if an audit
flags a false positive for a legitimate, less common region code."""

ISO_639_1 = {
    "aa", "ab", "ae", "af", "ak", "am", "an", "ar", "as", "av", "ay", "az",
    "ba", "be", "bg", "bh", "bi", "bm", "bn", "bo", "br", "bs",
    "ca", "ce", "ch", "co", "cr", "cs", "cu", "cv", "cy",
    "da", "de", "dv", "dz",
    "ee", "el", "en", "eo", "es", "et", "eu",
    "fa", "ff", "fi", "fj", "fo", "fr", "fy",
    "ga", "gd", "gl", "gn", "gu", "gv",
    "ha", "he", "hi", "ho", "hr", "ht", "hu", "hy", "hz",
    "ia", "id", "ie", "ig", "ii", "ik", "io", "is", "it", "iu",
    "ja", "jv",
    "ka", "kg", "ki", "kj", "kk", "kl", "km", "kn", "ko", "kr", "ks", "ku", "kv", "kw", "ky",
    "la", "lb", "lg", "li", "ln", "lo", "lt", "lu", "lv",
    "mg", "mh", "mi", "mk", "ml", "mn", "mr", "ms", "mt", "my",
    "na", "nb", "nd", "ne", "ng", "nl", "nn", "no", "nr", "nv", "ny",
    "oc", "oj", "om", "or", "os",
    "pa", "pi", "pl", "ps", "pt",
    "qu",
    "rm", "rn", "ro", "ru", "rw",
    "sa", "sc", "sd", "se", "sg", "si", "sk", "sl", "sm", "sn", "so", "sq", "sr", "ss", "st", "su", "sv", "sw",
    "ta", "te", "tg", "th", "ti", "tk", "tl", "tn", "to", "tr", "ts", "tt", "tw", "ty",
    "ug", "uk", "ur", "uz",
    "ve", "vi", "vo",
    "wa", "wo",
    "xh",
    "yi", "yo",
    "za", "zh", "zu",
}

ISO_3166_1 = {
    "us", "gb", "de", "fr", "es", "it", "pt", "nl", "be", "ch", "at", "se", "no", "dk", "fi",
    "ie", "pl", "cz", "sk", "hu", "ro", "bg", "gr", "hr", "si", "ee", "lv", "lt", "lu", "mt", "cy", "is",
    "ca", "mx", "br", "ar", "cl", "co", "pe", "uy", "ve", "ec", "bo", "py",
    "cn", "jp", "kr", "in", "id", "th", "vn", "ph", "my", "sg", "tw", "hk", "pk", "bd",
    "au", "nz",
    "ru", "ua", "by", "kz", "tr", "il", "sa", "ae", "eg", "za", "ng", "ke", "ma", "tn", "dz",
}
