"""
Rebuilds schools.js for the Hong Kong Island School Finder.

Run from the project folder:   python3 tools/prepare_data.py
Needs pypdf only for the P1 places booklet (pip install pypdf). Without it,
the script still runs and just leaves out the P1 places figures.

Inputs (all in data-raw/, all downloaded from Hong Kong government open data):
  edb_school_locations.json  every school, with map position   (EDB, data.gov.hk)
  poa_nets.geojson           Primary One Admission school net boundaries (EDB, CSDI portal)
  poa_school_lists.pdf       P1 "discretionary places quota" for each school, by net (EDB)
  sspa.csv                   which secondary school nets each secondary school serves (EDB)
  through_train.csv          primary + secondary schools run as one "through-train" (EDB)
  dssinfo.csv, dssfee.csv    Direct Subsidy Scheme schools and their fees (EDB)
  kg_profiles.csv            kindergarten profiles (EDB), UTF-16, "^" separated
  chsc_primary_profiles.csv  Primary School Profiles 2026, English (Committee on Home-School
                             Co-operation, data.gov.hk): teaching language, feeder and nominated
                             secondary schools, tests and exams, school hours, teachers, classes
  esr_reports.csv            External School Review reports (concluding chapter) published by the
                             EDB since 2023/24: school year, school name, link to the PDF. Built
                             from the three year pages linked from
                             https://www.edb.gov.hk/en/sch-admin/sch-quality-assurance/reports/esr-report/index.html
"""
import csv, io, json, re, os, datetime
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "..", "data-raw")
OUT = os.path.join(HERE, "..", "schools.js")

# The four districts that make up Hong Kong Island.
DISTRICTS = {"CENTRAL AND WESTERN": "Central and Western", "WAN CHAI": "Wan Chai",
             "EASTERN": "Eastern", "SOUTHERN": "Southern"}
# Primary One Admission (POA) school nets on Hong Kong Island.
HK_NETS = ["11", "12", "14", "16", "18"]
# Secondary (SSPA) school nets on Hong Kong Island. Each one is a whole district.
SSPA_NETS = {"HK1": "Central and Western", "HK2": "Wan Chai", "HK3": "Eastern", "HK4": "Southern"}


def raw(name):
    return os.path.join(RAW, name)


def clean(v):
    v = (v or "").strip()
    return "" if v in ("N.A.", "NOT APPLICABLE", "-") else v


def title(s):
    """'ST. PAUL'S COLLEGE' -> 'St. Paul's College', keeping short words like SKH, HK, TWGHS upper case."""
    keep = {"SKH", "HK", "TWGHS", "PLK", "YWCA", "YMCA", "ELCHK", "CCC", "HKFYG", "ESF", "CMA", "HKSKH",
            "STFA", "POH", "TWGHS", "KG", "II", "III", "ICS", "HKUGA", "CNEC", "SKMC", "BMCPC", "HKMA", "IB"}
    words = []
    for w in s.split():
        bare = re.sub(r"[^A-Z]", "", w)
        if bare in keep:
            words.append(w)
        else:
            words.append(w[:1] + w[1:].lower() if w[:1].isalpha() else w[:1] + w[1:2].upper() + w[2:].lower())
    return re.sub(r"'S\b", "'s", " ".join(words))


def norm(name):
    """Name key for matching across files: lower case, letters and digits only."""
    n = name.lower().replace("&", "and").replace("’", "'")
    n = re.sub(r"\bst\b\.?", "st", n)
    return re.sub(r"[^a-z0-9]", "", n)


# ---------- Point-in-polygon (for working out which net a point is in) ----------
def in_ring(lon, lat, ring):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def in_geometry(lon, lat, geom):
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    for poly in polys:
        if in_ring(lon, lat, poly[0]) and not any(in_ring(lon, lat, hole) for hole in poly[1:]):
            return True
    return False


# ---------- School nets ----------
nets_geo = json.load(open(raw("poa_nets.geojson"), encoding="utf-8"))
net_features = []
for f in nets_geo["features"]:
    p = f["properties"]
    if p["NAME"] not in HK_NETS:
        continue
    g = f["geometry"]
    # Round to 5 decimal places (about 1 metre) to keep the file small.
    rnd = lambda ring: [[round(x, 5), round(y, 5)] for x, y in ring]
    if g["type"] == "Polygon":
        g = {"type": "Polygon", "coordinates": [rnd(r) for r in g["coordinates"]]}
    else:
        g = {"type": "MultiPolygon", "coordinates": [[rnd(r) for r in poly] for poly in g["coordinates"]]}
    net_features.append({"type": "Feature", "geometry": g,
                         "properties": {"net": p["NAME"], "areas": title(p["AREA_EN"]), "areasZh": p["AREA_TC"].strip(),
                                        "link": p["WEBPAGE_EN"]}})
net_features.sort(key=lambda f: f["properties"]["net"])


def net_at(lon, lat):
    for f in net_features:
        if in_geometry(lon, lat, f["geometry"]):
            return f["properties"]["net"]
    return ""


# ---------- P1 places by school, from the EDB booklet (PDF) ----------
p1 = {}  # 6-digit school number -> {"net": "11", "quota": 25, "notes": [...]}
booklet_date = ""
try:
    import pypdf
    reader = pypdf.PdfReader(raw("poa_school_lists.pdf"))
    for page in reader.pages:
        text = page.extract_text()
        m = re.search(r"POA School Net\s*\n?\s*(\d{2})\s*\n", text)
        if not m or m.group(1) not in HK_NETS:
            continue
        net = m.group(1)
        d = re.search(r"(\d{1,2}/20\d\d)", text)
        if d:
            booklet_date = d.group(1)
        # Each school block starts with its 6-digit number at the start of a line.
        body = text.split("***")[0]
        blocks = re.split(r"\n(?=\d{6} )", body)
        for b in blocks:
            idm = re.match(r"(\d{6}) ", b)
            if not idm:
                continue
            # The quota is the number just before the Chinese address, which starts with 香港.
            q = re.search(r"(?:^|\s)(\d{2,3})\s+香港", b)
            codes = re.findall(r"\((S|P|U\d|#\d)\)", b.split("\n")[0])
            p1[idm.group(1)] = {"net": net, "quota": int(q.group(1)) if q else None,
                                "smallClass": "S" in codes, "disabledAccess": "P" in codes}
    print(f"P1 booklet: {len(p1)} Hong Kong Island primary schools")
except ImportError:
    print("pypdf is not installed, so P1 places are left out. Run: pip install pypdf")

# ---------- Secondary school nets served ----------
sspa = {}
with open(raw("sspa.csv"), encoding="utf-8-sig") as fh:
    for row in csv.DictReader(fh):
        serves = [n for n in ["HK1", "HK2", "HK3", "HK4", "KL1", "KL2", "KL3", "KL4", "KL5"] +
                  [f"NT{i}" for i in range(1, 10)] if (row.get(n) or "").strip() == "Y"]
        sspa[row["Sch Code"].strip()] = {"net": row["Net"].strip(), "serves": serves}

# ---------- Through-train pairs ----------
through = {}
with open(raw("through_train.csv"), encoding="utf-8-sig") as fh:
    groups = defaultdict(list)
    for row in csv.DictReader(fh):
        groups[row["GroupID"]].append(row["SchoolName"].strip())
    for names in groups.values():
        for n in names:
            through[norm(n)] = [x for x in names if x != n]

# ---------- DSS fees ----------
dss_fees = defaultdict(list)
with open(raw("dssfee.csv"), encoding="utf-8-sig") as fh:
    for row in csv.reader(fh):
        if not row or not row[0].strip().isdigit():
            continue
        name, level, cls, lo, hi = row[1], row[2], row[3], row[5], row[6]
        fee = f"HK${int(lo):,}" if lo == hi else f"HK${int(lo):,}–{int(hi):,}"
        dss_fees[norm(name)].append([f"{level} {cls}", fee])

# ---------- Kindergarten profiles ----------
kg = {}
text = open(raw("kg_profiles.csv"), encoding="utf-16").read()
rows = list(csv.reader(io.StringIO(text), delimiter="^"))
head = rows[0]
for r in rows[1:]:
    if len(r) < len(head) - 5:
        continue
    d = dict(zip(head, r))
    key = d["school_no"].strip()
    if key in kg:
        continue
    def num(k):
        try:
            return int(d.get(k, "0") or 0)
        except ValueError:
            return 0
    pupils = sum(num(k) for k in head if k.startswith("no_of_students_in") or k.startswith("no_of_students_ukg"))
    qr = d.get("quality_review_result_and_report_eng ", d.get("quality_review_result_and_report_eng", "")).strip()
    qr_link = re.search(r"https?://\S+", qr)
    kg[key] = {
        "scheme": d["joining_kg_edu_scheme"].strip() == "Joining",
        "applyFrom": d["application_date_from"].strip(), "applyTo": d["application_date_to"].strip(),
        "applyHow": d["application_period_type"].strip(),
        "curriculum": d["curriculum_type"].strip(),
        "category": d["school_category"].strip(),
        "founded": d["school_founding_year"].strip(),
        "ratioAm": d.get("teacher_to_pupil_ratio_in_morning_session", "").strip(),
        "ratioPm": d.get("teacher_to_pupil_ratio_in_afternoon_session", "").strip(),
        "degreeStaff": num("no_of_principal_and_teaching_staff_with_degree"),
        "totalStaff": num("total_no_of_principal_and_teaching_staff"),
        "pupils": pupils,
        "feesLink": d.get("fees_certificate", "").strip(),
        "review": re.sub(r"\s*https?://\S+", "", qr).strip(),
        "reviewLink": qr_link.group(0) if qr_link else "",
        "ncsSupport": d.get("received_grant_for_support_to_ncs_students", "").strip() == "Y",
        "website": d.get("school_website", "").strip(),
    }

# ---------- Primary School Profiles (CHSC) ----------
# This file has no EDB school number, so we match on the school name, and if that
# fails, on the phone number.
def plain(v):
    """Tidy a profile text field: drop '<br>' tags and the '-' used for 'nothing'."""
    v = re.sub(r"\s*<br\s*/?>\s*", " ", (v or "")).strip()
    v = re.sub(r"\s+", " ", v).strip('"').strip()
    return "" if v in ("-", "N.A.", "Not Applicable.", "Not applicable") else v


def short(v, limit=320):
    """Cut long paragraphs so the panel stays readable; the full text is on chsc.hk."""
    v = plain(v)
    return v if len(v) <= limit else v[:limit].rsplit(" ", 1)[0] + "…"


psp_by_name, psp_by_phone = {}, {}
with open(raw("chsc_primary_profiles.csv"), encoding="utf-8-sig") as fh:
    for d in csv.DictReader(fh):
        if d["district"] not in ("Central & Western", "Wan Chai", "Eastern", "Southern"):
            continue
        cls = [plain(d.get(f"current_year_no_of_class_p{i}")) for i in range(1, 7)]
        start = plain(d["school_starts_at"]) and f'{plain(d["school_starts_at"])} {plain(d["school_starts_at_AMPM"])}'.lower()
        end = plain(d["school_ends_at"]) and f'{plain(d["school_ends_at"])} {plain(d["school_ends_at_AMPM"])}'.lower()
        p = {
            "moi": plain(d["medium_of_instruction"]),
            "throughTrain": plain(d["through_train_sec_school"]),
            "feeder": plain(d["feeder_sec_school"]),
            "nominated": plain(d["nominated_sec_school"]),
            "sponsor": plain(d["sponsoring_body"]),
            "founded": plain(d["commencement_of_operation_year"]),
            "classes": cls if any(cls) else [],
            "classesTotal": plain(d["current_year_no_of_class_total"]),
            "testsP1": plain(d["no_of_test_per_year_P1"]), "examsP1": plain(d["no_of_exam_per_year_P1"]),
            "testsP2": plain(d["no_of_test_per_year_P2-P6"]), "examsP2": plain(d["no_of_exam_P2-P6"]),
            "hours": f"{start} to {end}" if start and end else "",
            "lunch": plain(d["lunch_arrangement"]),
            "bus": plain(d["school_bus"]) == "Yes", "nannyVan": plain(d["nanny_van"]) == "Yes",
            "teachers": plain(d["previous_year_tsi_total_no_of_teachers"]),
            "pctMasters": plain(d["previous_year_tsi_percent_of_master_doctorate_or_above"]),
            "pctExp10": plain(d["previous_year_tsi_percent_of_exp_10_or_above"]),
            "pctSen": plain(d["previous_year_tsi_percent_of_special_edu_training"]),
            "streaming": short(d["streaming_arrangement"], 200),
            "ncs": short(d["support_for_non_chinese_students"]),
            "schoolFee": plain(d["asc_school_fee"]), "tongFai": plain(d["asc_tong_fai"]),
            "ptaFee": plain(d["asc_pta_fee"]),
        }
        psp_by_name[norm(d["school_name"])] = p
        psp_by_phone[re.sub(r"\D", "", d["school_tel"])] = p

# ---------- External School Review reports (the nearest thing to Ofsted reports) ----------
# The EDB's list gives "English name 中文名", so we match on the start of the name.
esr = defaultdict(list)
with open(raw("esr_reports.csv"), encoding="utf-8") as fh:
    for row in csv.DictReader(fh):
        english = re.split(r"[一-鿿]", row["school_name"])[0]
        esr[norm(english)].append({"year": row["school_year"], "url": row["report_url"]})
for reports in esr.values():
    reports.sort(key=lambda r: r["year"], reverse=True)  # newest first

# ---------- Schools ----------
FINANCE = {"GOVERNMENT": "Government", "AIDED": "Aided", "DIRECT SUBSIDY SCHEME": "DSS",
           "ENGLISH SCHOOLS FOUNDATION": "ESF", "PRIVATE INDEPENDENT SCH SCHEME": "Private (PIS)", "PRIVATE": "Private"}
LEVEL = {"PRIMARY": "Primary", "SECONDARY": "Secondary", "KINDERGARTEN": "Kindergarten",
         "KINDERGARTEN-CUM-CHILD CARE CENTRES": "Kindergarten"}

data = json.load(open(raw("edb_school_locations.json"), encoding="utf-8"))
schools = {}
for x in data:
    if x["DISTRICT"] not in DISTRICTS:
        continue
    num6 = str(x["SCHOOL NO."])[:6]
    cat = x["ENGLISH CATEGORY"]
    key = num6 + "-" + cat
    session = x["SESSION"].title().replace("A.M.", "Morning").replace("P.M.", "Afternoon")
    session = {"A.M.": "Morning", "P.M.": "Afternoon"}.get(x["SESSION"], session)
    if key in schools:
        if session not in schools[key]["sessions"]:
            schools[key]["sessions"].append(session)
        continue
    finance = FINANCE.get(x["FINANCE TYPE"], x["FINANCE TYPE"].title())
    if "International" in cat:
        finance = "International"
    level = LEVEL.get(x["SCHOOL LEVEL"], x["SCHOOL LEVEL"].title())
    special = "Special" in cat
    if level == "Kindergarten":
        kind = "kg"
    elif special:
        kind = "special"
    else:
        kind = {"Government": "gov", "Aided": "aided", "DSS": "dss", "ESF": "esf",
                "International": "intl"}.get(finance, "private")
    s = {
        "id": key, "schoolNo": num6, "name": title(x["ENGLISH NAME"]), "nameZh": x["中文名稱"],
        "category": cat, "level": level, "finance": finance, "kind": kind, "special": special,
        "gender": {"CO-ED": "Co-ed", "BOYS": "Boys", "GIRLS": "Girls"}.get(x["STUDENTS GENDER"], x["STUDENTS GENDER"].title()),
        "sessions": [session], "district": DISTRICTS[x["DISTRICT"]],
        "religion": title(clean(x["RELIGION"])).replace(" / ", " / "),
        "address": title(x["ENGLISH ADDRESS"]), "addressZh": x["中文地址"],
        "phone": clean(x["TELEPHONE"]), "website": clean(x["WEBSITE"]).lower(),
        "lat": round(x["LATITUDE"], 6), "lon": round(x["LONGITUDE"], 6),
    }
    s["netHere"] = net_at(s["lon"], s["lat"])  # which P1 school net the building is in
    if level == "Primary" and finance in ("Government", "Aided") and not special:
        info = p1.get(num6)
        s["inPOA"] = True
        s["poaNet"] = info["net"] if info else s["netHere"]
        if info:
            s["dpQuota"] = info["quota"]
            s["smallClass"] = info["smallClass"]
            s["disabledAccess"] = info["disabledAccess"]
        elif p1:
            # The booklet only lists schools expected to open P1 classes next year.
            s["notInBooklet"] = True
    if level == "Secondary" and num6 in sspa:
        s["sspaNet"] = sspa[num6]["net"]
        s["sspaServes"] = sspa[num6]["serves"]
    partners = through.get(norm(s["name"]))
    if partners:
        s["throughTrain"] = partners
    if finance == "DSS" and norm(s["name"]) in dss_fees:
        s["fees"] = dss_fees[norm(s["name"])]
    if level == "Primary" and not special:
        prof = psp_by_name.get(norm(s["name"])) or psp_by_phone.get(re.sub(r"\D", "", s["phone"]))
        if prof:
            s["psp"] = prof
    if level != "Kindergarten" and norm(s["name"]) in esr:
        s["esr"] = esr[norm(s["name"])]
    if level == "Kindergarten" and num6 in kg:
        s["kg"] = kg[num6]
        if not s["website"] and kg[num6]["website"]:
            s["website"] = kg[num6]["website"].lower()
    schools[key] = s

out = sorted(schools.values(), key=lambda s: s["name"])
missing_p1 = [s["name"] for s in out if s.get("inPOA") and "dpQuota" not in s]
if missing_p1:
    print("Government/aided primaries with no P1 places figure:", missing_p1)
print(f"{len(out)} schools; by type:", dict(sorted(defaultdict(int, {k: sum(1 for s in out if s['kind'] == k) for k in set(s['kind'] for s in out)}).items())))
print("Through-train matches:", sum(1 for s in out if "throughTrain" in s), "| DSS fee matches:", sum(1 for s in out if "fees" in s),
      "| KG profiles:", sum(1 for s in out if "kg" in s), "| SSPA:", sum(1 for s in out if "sspaNet" in s),
      "| Review reports:", sum(1 for s in out if "esr" in s),
      "| Primary profiles:", sum(1 for s in out if "psp" in s), "of", len(psp_by_name))

info = {"built": datetime.date.today().strftime("%-d %b %Y"), "p1Booklet": booklet_date,
        "districts": list(DISTRICTS.values()), "sspaNets": SSPA_NETS}
with open(OUT, "w", encoding="utf-8") as fh:
    fh.write("// Generated by tools/prepare_data.py - do not edit by hand.\n")
    fh.write("const DATA_INFO = " + json.dumps(info, ensure_ascii=False) + ";\n")
    fh.write("const POA_NETS = " + json.dumps({"type": "FeatureCollection", "features": net_features}, ensure_ascii=False, separators=(",", ":")) + ";\n")
    fh.write("const SCHOOLS = [\n" + ",\n".join(json.dumps(s, ensure_ascii=False, separators=(",", ":")) for s in out) + "\n];\n")
print("Wrote", OUT, os.path.getsize(OUT) // 1024, "KB")
