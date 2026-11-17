"""Pull the live series for each dashboard and save them as JSON in site/data/.

Sources
  FRED  - public CSV download, no key needed. Most series live here.
  DOLWD - the Alaska Department of Labor's payroll-jobs CSV. Its own monthly
          estimates, which are what Alaska news reports and can differ from the
          federal (BLS/FRED) numbers for the latest months.
  BLS   - the BLS public API. Used only for Urban Alaska CPI detail, which FRED
          carries just twice a year. Works without a key (25 requests a day,
          shared by everyone on GitHub's servers); add a free key as the
          BLS_API_KEY secret to make it dependable.
  EIA   - the EIA API (v2). Retail electricity prices by state and sector, and
          natural gas prices by state and customer type (city gate, homes,
          businesses, power plants). Needs a free key as the EIA_API_KEY
          secret; without one the EIA dashboards are skipped with a warning and
          nothing else is affected.
  Census - the Census Bureau data API. Annual counts of businesses by industry
          (County Business Patterns for employers, Nonemployer Statistics for
          owner-operators). Used for food trucks (NAICS 722330). No key needed;
          add one as the CENSUS_API_KEY secret if requests are ever refused.
  BDS   - the Census Bureau's Business Dynamics Statistics, read from its
          published CSV tables (no key). Annual firm startups, deaths and
          establishment entry for Alaska and the U.S. since 1978, plus entry
          by industry. Firm entry rate = age-0 firms / all firms.

Standard library only, so GitHub Actions can run it without installing anything.

Hand-maintained numbers (annual reports, surveys, budgets) are not here: they
live in site/data/manual/<dashboard>.json and you edit them directly.

Usage:
    python scripts/fetch_data.py            # fetch every dashboard
    python scripts/fetch_data.py housing    # fetch just one
"""
import csv
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "site" / "data"
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"
BLS_V1 = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
BLS_V2 = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
EIA_RETAIL = "https://api.eia.gov/v2/electricity/retail-sales/data/"
EIA_GAS = "https://api.eia.gov/v2/natural-gas/pri/sum/data/"
CENSUS_API = "https://api.census.gov/data/{year}/{dataset}"
DOLWD_CES = "https://live.laborstats.alaska.gov/labforce/csv/000000/01/ces.csv"
UA = {"User-Agent": "twocentsforalaska.org data refresh (github.com/sg23234/twocentsforalaska)"}

def s(label, units, freq, kind, optional=False):
    """Series metadata. kind: level | flow (counts you can add up) | index | rate | pct."""
    return {"label": label, "units": units, "freq": freq, "kind": kind, "optional": optional}


# dashboard slug -> {"source": ..., "series": {id: metadata}}
# optional=True: try it, but a failure is only a warning (used for series whose
# FRED ID we couldn't confirm ahead of time; the page copes without them).
DASHBOARDS = {
    "current-account": {"source": "fred", "series": {
        "AKNGSP": s("GDP, current dollars, annual", "millions of dollars", "annual", "level"),
        "AKPCE": s("Personal consumption expenditures by state of residence", "millions of dollars", "annual", "level"),
        "AKODIV": s("Dividends, interest and rent received by Alaskans, SAAR", "millions of dollars, annual rate", "quarterly", "level"),
        "AKGOVSLNGSP": s("GDP, state and local government", "millions of dollars", "annual", "level"),
        "AKGOVFEDCIVNGSP": s("GDP, federal civilian", "millions of dollars", "annual", "level"),
        "AKGOVFEDMILNGSP": s("GDP, military", "millions of dollars", "annual", "level", optional=True),
        "AKOILGASNGSP": s("GDP, oil and gas extraction", "millions of dollars", "annual", "level"),
        "AKMINNGSP": s("GDP, mining incl. oil and gas", "millions of dollars", "annual", "level"),
        "AKPINGSP": s("GDP, private industries", "millions of dollars", "annual", "level"),
        "AKEADJ": s("Residence adjustment, SAAR", "thousands of dollars, annual rate", "quarterly", "level", optional=True),
    }},
    "gdp": {"source": "fred", "series": {
        "AKRGSP": s("Real GDP, annual, millions of chained 2017 dollars", "millions of 2017 dollars", "annual", "level"),
        "AKRQGSP": s("Real GDP, quarterly SAAR, millions of chained 2017 dollars", "millions of 2017 dollars, annual rate", "quarterly", "level"),
        "AKMINRQGSP": s("Real GDP, mining (incl. oil & gas), quarterly SAAR", "millions of 2017 dollars, annual rate", "quarterly", "level"),
        "AKGOVRQGSP": s("Real GDP, government, quarterly SAAR", "millions of 2017 dollars, annual rate", "quarterly", "level"),
    }},
    "population": {"source": "fred", "series": {
        "AKPOP": s("Resident population (Census Bureau estimate, July 1)", "thousands of people", "annual", "level"),
    }},
    "business-formation": {"source": "fred", "series": {
        "BABATOTALNSAAK": s("Business applications, Alaska", "applications", "monthly", "flow"),
        "BAHBATOTALNSAAK": s("High-propensity business applications (likely employers), Alaska", "applications", "monthly", "flow", optional=True),
        "BABATOTALNSAUS": s("Business applications, United States", "applications", "monthly", "flow", optional=True),
    }},
    "housing": {"source": "fred", "series": {
        "AKBPPRIV": s("New private housing units authorized by building permits, Alaska", "units", "monthly", "flow"),
        "MORTGAGE30US": s("30-year fixed mortgage rate, U.S. average (Freddie Mac)", "percent", "weekly", "rate"),
        "AKSTHPI": s("All-transactions house price index, Alaska (FHFA)", "index 1980Q1=100", "quarterly", "index", optional=True),
        "USSTHPI": s("All-transactions house price index, United States (FHFA)", "index 1980Q1=100", "quarterly", "index", optional=True),
    }},
    "cost-of-living": {"source": "bls", "soft": True, "series": {
        "CUURS49GSA0": s("CPI, all items, Urban Alaska", "index 1982-84=100", "bimonthly", "index"),
        "CUURS49GSA0L1E": s("CPI, all items less food and energy, Urban Alaska", "index", "bimonthly", "index"),
        "CUURS49GSETB": s("CPI, motor fuel, Urban Alaska", "index", "bimonthly", "index"),
        "CUURS49GSETB01": s("CPI, gasoline (all types), Urban Alaska", "index", "bimonthly", "index", optional=True),
        "CUURS49GSAR": s("CPI, recreation, Urban Alaska", "index", "bimonthly", "index"),
        "CUURS49GSAT": s("CPI, transportation, Urban Alaska", "index", "bimonthly", "index"),
        "CUURS49GSAG": s("CPI, other goods and services, Urban Alaska", "index", "bimonthly", "index"),
        "CUURS49GSAH1": s("CPI, shelter, Urban Alaska", "index", "bimonthly", "index"),
        "CUURS49GSEHC": s("CPI, owners' equivalent rent, Urban Alaska", "index", "bimonthly", "index", optional=True),
        "CUURS49GSAH": s("CPI, housing, Urban Alaska", "index", "bimonthly", "index"),
        "CUURS49GSEHA": s("CPI, rent of primary residence, Urban Alaska", "index", "bimonthly", "index", optional=True),
        "CUURS49GSAF11": s("CPI, food at home, Urban Alaska", "index", "bimonthly", "index"),
        "CUURS49GSEFV": s("CPI, food away from home, Urban Alaska", "index", "bimonthly", "index"),
        "CUURS49GSAA": s("CPI, apparel, Urban Alaska", "index", "bimonthly", "index"),
        "CUURS49GSAE": s("CPI, education and communication, Urban Alaska", "index", "bimonthly", "index"),
        "CUURS49GSAM": s("CPI, medical care, Urban Alaska", "index", "bimonthly", "index"),
        "CUURS49GSAH3": s("CPI, household furnishings and operations, Urban Alaska", "index", "bimonthly", "index"),
        "CUURS49GSETA": s("CPI, new and used motor vehicles, Urban Alaska", "index", "bimonthly", "index", optional=True),
        "CUUR0000SA0": s("CPI, all items, U.S. city average", "index 1982-84=100", "monthly", "index"),
    }},
    "productivity": {"source": "fred", "series": {
        "IPUZNL000020000": s("Labor productivity, private nonfarm, Alaska", "index 2017=100", "annual", "index"),
        "IPUZNT010020000": s("Real value-added output, private nonfarm, Alaska", "index 2017=100", "annual", "index"),
        "IPUZNL010020000": s("Hours worked, private nonfarm, Alaska", "index 2017=100", "annual", "index"),
    }},
    # Payroll jobs straight from Alaska DOLWD (not seasonally adjusted). Keyed by
    # the industry name exactly as it appears in DOLWD's CSV.
    "key-sectors": {"source": "dolwd", "soft": True, "series": {
        "Total Nonfarm": s("Payroll jobs, total nonfarm", "jobs", "monthly", "level"),
        "Trade, Transportation, Utilities": s("Payroll jobs, trade, transportation and utilities", "jobs", "monthly", "level"),
        "Construction": s("Payroll jobs, construction", "jobs", "monthly", "level"),
        "Mining and Logging": s("Payroll jobs, mining and logging (includes oil and gas)", "jobs", "monthly", "level"),
        "Oil & Gas": s("Payroll jobs, oil and gas", "jobs", "monthly", "level"),
        "Health Care": s("Payroll jobs, health care", "jobs", "monthly", "level"),
        "Manufacturing": s("Payroll jobs, manufacturing (mostly seafood processing)", "jobs", "monthly", "level"),
        "Information": s("Payroll jobs, information", "jobs", "monthly", "level"),
        "Leisure & Hospitality": s("Payroll jobs, leisure and hospitality", "jobs", "monthly", "level"),
        "Financial Activities": s("Payroll jobs, financial activities", "jobs", "monthly", "level"),
        "Professional & Business Svcs": s("Payroll jobs, professional and business services", "jobs", "monthly", "level"),
        "Local Government": s("Payroll jobs, local government (incl. schools)", "jobs", "monthly", "level"),
        "State Government": s("Payroll jobs, state government", "jobs", "monthly", "level"),
        "Federal Government": s("Payroll jobs, federal government (civilian)", "jobs", "monthly", "level"),
    }},
    # ANC air cargo page: BLS state payroll detail via FRED, thousands of jobs,
    # not seasonally adjusted. Optional so a FRED hiccup only warns.
    "air-cargo": {"source": "fred", "series": {
        "SMU02000004348100001": s("Payroll jobs, air transportation, Alaska", "thousands of jobs", "monthly", "level", optional=True),
        "SMU02000004340008901": s("Payroll jobs, transportation and warehousing, Alaska", "thousands of jobs", "monthly", "level", optional=True),
        # BLS inbound air freight price index, Asia to the U.S. (U.S. and foreign carriers)
        "IC1312": s("Inbound air freight price index, Asia", "index", "monthly", "index", optional=True),
    }},
    "labor": {"source": "fred", "series": {
        "LBSSA02": s("Labor force participation rate, Alaska", "percent", "monthly", "rate"),
        "CIVPART": s("Labor force participation rate, United States", "percent", "monthly", "rate"),
        "AKUR": s("Unemployment rate, Alaska", "percent", "monthly", "rate"),
        "UNRATE": s("Unemployment rate, United States", "percent", "monthly", "rate"),
        "SMU02000000500000003": s("Average hourly earnings, all private employees, Alaska", "dollars", "monthly", "level", optional=True),
        "CES0500000003": s("Average hourly earnings, all private employees, United States", "dollars", "monthly", "level", optional=True),
    }},
    # Retail electricity price, cents per kWh, keyed "<state>-<sector>".
    # Sectors: COM commercial, RES residential, IND industrial, ALL all sectors.
    "energy": {"source": "eia", "soft": True, "series": {
        "AK-ALL": s("Average retail electricity price, all sectors, Alaska", "cents per kWh", "monthly", "rate"),
        "US-ALL": s("Average retail electricity price, all sectors, United States", "cents per kWh", "monthly", "rate", optional=True),
        "AK-COM": s("Average retail electricity price, commercial, Alaska", "cents per kWh", "monthly", "rate", optional=True),
        "AK-RES": s("Average retail electricity price, residential, Alaska", "cents per kWh", "monthly", "rate", optional=True),
        "AK-ALL:sales": s("Retail electricity sales, all sectors, Alaska", "million kWh", "monthly", "flow", optional=True),
        "US-ALL:sales": s("Retail electricity sales, all sectors, United States", "million kWh", "monthly", "flow", optional=True),
    }},
    # Natural gas prices, dollars per thousand cubic feet, keyed "<area>-<type>".
    # Each maps to an EIA series ID (N30x0 + state + 3 = monthly). City gate is
    # what local gas utilities (Enstar in Southcentral) pay for gas delivered to
    # their system; the others are what each kind of customer pays, all-in.
    # All optional: EIA withholds some Alaska months, and a miss only warns.
    "natural-gas": {"source": "eia_gas", "soft": True, "series": {
        "AK-CITYGATE": s("Natural gas city gate price, Alaska", "dollars per Mcf", "monthly", "rate", optional=True),
        "US-CITYGATE": s("Natural gas city gate price, United States", "dollars per Mcf", "monthly", "rate", optional=True),
        "AK-RES": s("Natural gas price, residential customers, Alaska", "dollars per Mcf", "monthly", "rate", optional=True),
        "US-RES": s("Natural gas price, residential customers, United States", "dollars per Mcf", "monthly", "rate", optional=True),
        "AK-COM": s("Natural gas price, commercial customers, Alaska", "dollars per Mcf", "monthly", "rate", optional=True),
        "US-COM": s("Natural gas price, commercial customers, United States", "dollars per Mcf", "monthly", "rate", optional=True),
        "AK-ELEC": s("Natural gas price, electric power plants, Alaska", "dollars per Mcf", "monthly", "rate", optional=True),
        "US-ELEC": s("Natural gas price, electric power plants, United States", "dollars per Mcf", "monthly", "rate", optional=True),
    }},
    # Food trucks: Census counts for NAICS 722330 (mobile food services), keyed
    # "<dataset>-<geo>:<variable>". cbp = employer establishments (County Business
    # Patterns); nonemp = businesses with no employees (Nonemployer Statistics).
    # All optional: small Alaska cells can be withheld, and a miss only warns.
    "food-trucks": {"source": "census", "naics": "722330", "series": {
        "cbp-AK:ESTAB": s("Mobile food services establishments with employees, Alaska (County Business Patterns)", "establishments", "annual", "level", optional=True),
        "cbp-AK:EMP": s("Employees at mobile food services establishments, Alaska, mid-March", "jobs", "annual", "level", optional=True),
        "nonemp-AK:NESTAB": s("Mobile food services businesses without employees, Alaska (Nonemployer Statistics)", "businesses", "annual", "level", optional=True),
        "cbp-US:ESTAB": s("Mobile food services establishments with employees, United States", "establishments", "annual", "level", optional=True),
        "nonemp-US:NESTAB": s("Mobile food services businesses without employees, United States", "businesses", "annual", "level", optional=True),
    }},
    # Business Dynamics Statistics (Census), annual, keyed "<measure>-<AK|US>".
    # Sector rows ("SEC<code>:<measure>-<geo>") feed the industry table on /firm-entry/.
    "firm-dynamics": {"source": "bds", "soft": True, "series": {
        "FIRM_ENTRY_RATE-AK": s("Firm entry rate (new employer firms as a share of all firms), Alaska", "percent", "annual", "rate"),
        "FIRM_ENTRY_RATE-US": s("Firm entry rate (new employer firms as a share of all firms), United States", "percent", "annual", "rate"),
        "STARTUPS-AK": s("New employer firms (age 0), Alaska", "firms", "annual", "flow"),
        "STARTUPS-US": s("New employer firms (age 0), United States", "firms", "annual", "flow"),
        "FIRMS-AK": s("Employer firms, Alaska", "firms", "annual", "level"),
        "FIRMS-US": s("Employer firms, United States", "firms", "annual", "level"),
        "STARTUP_EMP-AK": s("Employment at new (age 0) firms, Alaska, March", "jobs", "annual", "level", optional=True),
        "STARTUP_EMP_SHARE-AK": s("Employment at new (age 0) firms as a share of all employment, Alaska", "percent", "annual", "pct", optional=True),
        "STARTUP_EMP_SHARE-US": s("Employment at new (age 0) firms as a share of all employment, United States", "percent", "annual", "pct"),
        "ESTAB_ENTRY_RATE-AK": s("Establishment entry rate, Alaska", "percent", "annual", "rate"),
        "ESTAB_ENTRY_RATE-US": s("Establishment entry rate, United States", "percent", "annual", "rate"),
        "FIRM_EXIT_RATE-AK": s("Firm exit rate (firm deaths as a share of all firms), Alaska", "percent", "annual", "rate", optional=True),
        "FIRM_EXIT_RATE-US": s("Firm exit rate (firm deaths as a share of all firms), United States", "percent", "annual", "rate", optional=True),
        "YOUNG_EMP_SHARE-AK": s("Employment at firms aged 0-5 as a share of all employment, Alaska", "percent", "annual", "pct", optional=True),
        "YOUNG_EMP_SHARE-US": s("Employment at firms aged 0-5 as a share of all employment, United States", "percent", "annual", "pct", optional=True),
        "SEC11:ESTAB_ENTRY_RATE-AK": s("Establishment entry rate, Agriculture, forestry, fishing, Alaska", "percent", "annual", "rate", optional=True),
        "SEC11:ESTAB_ENTRY_RATE-US": s("Establishment entry rate, Agriculture, forestry, fishing, United States", "percent", "annual", "rate", optional=True),
        "SEC11:ESTABS-AK": s("Establishments, Agriculture, forestry, fishing, Alaska", "establishments", "annual", "level", optional=True),
        "SEC21:ESTAB_ENTRY_RATE-AK": s("Establishment entry rate, Mining, oil and gas, Alaska", "percent", "annual", "rate", optional=True),
        "SEC21:ESTAB_ENTRY_RATE-US": s("Establishment entry rate, Mining, oil and gas, United States", "percent", "annual", "rate", optional=True),
        "SEC21:ESTABS-AK": s("Establishments, Mining, oil and gas, Alaska", "establishments", "annual", "level", optional=True),
        "SEC22:ESTAB_ENTRY_RATE-AK": s("Establishment entry rate, Utilities, Alaska", "percent", "annual", "rate", optional=True),
        "SEC22:ESTAB_ENTRY_RATE-US": s("Establishment entry rate, Utilities, United States", "percent", "annual", "rate", optional=True),
        "SEC22:ESTABS-AK": s("Establishments, Utilities, Alaska", "establishments", "annual", "level", optional=True),
        "SEC23:ESTAB_ENTRY_RATE-AK": s("Establishment entry rate, Construction, Alaska", "percent", "annual", "rate", optional=True),
        "SEC23:ESTAB_ENTRY_RATE-US": s("Establishment entry rate, Construction, United States", "percent", "annual", "rate", optional=True),
        "SEC23:ESTABS-AK": s("Establishments, Construction, Alaska", "establishments", "annual", "level", optional=True),
        "SEC31-33:ESTAB_ENTRY_RATE-AK": s("Establishment entry rate, Manufacturing, Alaska", "percent", "annual", "rate", optional=True),
        "SEC31-33:ESTAB_ENTRY_RATE-US": s("Establishment entry rate, Manufacturing, United States", "percent", "annual", "rate", optional=True),
        "SEC31-33:ESTABS-AK": s("Establishments, Manufacturing, Alaska", "establishments", "annual", "level", optional=True),
        "SEC42:ESTAB_ENTRY_RATE-AK": s("Establishment entry rate, Wholesale trade, Alaska", "percent", "annual", "rate", optional=True),
        "SEC42:ESTAB_ENTRY_RATE-US": s("Establishment entry rate, Wholesale trade, United States", "percent", "annual", "rate", optional=True),
        "SEC42:ESTABS-AK": s("Establishments, Wholesale trade, Alaska", "establishments", "annual", "level", optional=True),
        "SEC44-45:ESTAB_ENTRY_RATE-AK": s("Establishment entry rate, Retail trade, Alaska", "percent", "annual", "rate", optional=True),
        "SEC44-45:ESTAB_ENTRY_RATE-US": s("Establishment entry rate, Retail trade, United States", "percent", "annual", "rate", optional=True),
        "SEC44-45:ESTABS-AK": s("Establishments, Retail trade, Alaska", "establishments", "annual", "level", optional=True),
        "SEC48-49:ESTAB_ENTRY_RATE-AK": s("Establishment entry rate, Transportation and warehousing, Alaska", "percent", "annual", "rate", optional=True),
        "SEC48-49:ESTAB_ENTRY_RATE-US": s("Establishment entry rate, Transportation and warehousing, United States", "percent", "annual", "rate", optional=True),
        "SEC48-49:ESTABS-AK": s("Establishments, Transportation and warehousing, Alaska", "establishments", "annual", "level", optional=True),
        "SEC51:ESTAB_ENTRY_RATE-AK": s("Establishment entry rate, Information, Alaska", "percent", "annual", "rate", optional=True),
        "SEC51:ESTAB_ENTRY_RATE-US": s("Establishment entry rate, Information, United States", "percent", "annual", "rate", optional=True),
        "SEC51:ESTABS-AK": s("Establishments, Information, Alaska", "establishments", "annual", "level", optional=True),
        "SEC52:ESTAB_ENTRY_RATE-AK": s("Establishment entry rate, Finance and insurance, Alaska", "percent", "annual", "rate", optional=True),
        "SEC52:ESTAB_ENTRY_RATE-US": s("Establishment entry rate, Finance and insurance, United States", "percent", "annual", "rate", optional=True),
        "SEC52:ESTABS-AK": s("Establishments, Finance and insurance, Alaska", "establishments", "annual", "level", optional=True),
        "SEC53:ESTAB_ENTRY_RATE-AK": s("Establishment entry rate, Real estate, Alaska", "percent", "annual", "rate", optional=True),
        "SEC53:ESTAB_ENTRY_RATE-US": s("Establishment entry rate, Real estate, United States", "percent", "annual", "rate", optional=True),
        "SEC53:ESTABS-AK": s("Establishments, Real estate, Alaska", "establishments", "annual", "level", optional=True),
        "SEC54:ESTAB_ENTRY_RATE-AK": s("Establishment entry rate, Professional services, Alaska", "percent", "annual", "rate", optional=True),
        "SEC54:ESTAB_ENTRY_RATE-US": s("Establishment entry rate, Professional services, United States", "percent", "annual", "rate", optional=True),
        "SEC54:ESTABS-AK": s("Establishments, Professional services, Alaska", "establishments", "annual", "level", optional=True),
        "SEC56:ESTAB_ENTRY_RATE-AK": s("Establishment entry rate, Administrative and support, Alaska", "percent", "annual", "rate", optional=True),
        "SEC56:ESTAB_ENTRY_RATE-US": s("Establishment entry rate, Administrative and support, United States", "percent", "annual", "rate", optional=True),
        "SEC56:ESTABS-AK": s("Establishments, Administrative and support, Alaska", "establishments", "annual", "level", optional=True),
        "SEC61:ESTAB_ENTRY_RATE-AK": s("Establishment entry rate, Education, Alaska", "percent", "annual", "rate", optional=True),
        "SEC61:ESTAB_ENTRY_RATE-US": s("Establishment entry rate, Education, United States", "percent", "annual", "rate", optional=True),
        "SEC61:ESTABS-AK": s("Establishments, Education, Alaska", "establishments", "annual", "level", optional=True),
        "SEC62:ESTAB_ENTRY_RATE-AK": s("Establishment entry rate, Health care and social assistance, Alaska", "percent", "annual", "rate", optional=True),
        "SEC62:ESTAB_ENTRY_RATE-US": s("Establishment entry rate, Health care and social assistance, United States", "percent", "annual", "rate", optional=True),
        "SEC62:ESTABS-AK": s("Establishments, Health care and social assistance, Alaska", "establishments", "annual", "level", optional=True),
        "SEC71:ESTAB_ENTRY_RATE-AK": s("Establishment entry rate, Arts and recreation, Alaska", "percent", "annual", "rate", optional=True),
        "SEC71:ESTAB_ENTRY_RATE-US": s("Establishment entry rate, Arts and recreation, United States", "percent", "annual", "rate", optional=True),
        "SEC71:ESTABS-AK": s("Establishments, Arts and recreation, Alaska", "establishments", "annual", "level", optional=True),
        "SEC72:ESTAB_ENTRY_RATE-AK": s("Establishment entry rate, Accommodation and food, Alaska", "percent", "annual", "rate", optional=True),
        "SEC72:ESTAB_ENTRY_RATE-US": s("Establishment entry rate, Accommodation and food, United States", "percent", "annual", "rate", optional=True),
        "SEC72:ESTABS-AK": s("Establishments, Accommodation and food, Alaska", "establishments", "annual", "level", optional=True),
        "SEC81:ESTAB_ENTRY_RATE-AK": s("Establishment entry rate, Other services, Alaska", "percent", "annual", "rate", optional=True),
        "SEC81:ESTAB_ENTRY_RATE-US": s("Establishment entry rate, Other services, United States", "percent", "annual", "rate", optional=True),
        "SEC81:ESTABS-AK": s("Establishments, Other services, Alaska", "establishments", "annual", "level", optional=True),
    }},
    # Indeed Hiring Lab job postings index (Feb 1, 2020 = 100, seasonally adjusted),
    # published daily on GitHub; kept here as monthly averages (the latest month is month to date).
    "job-postings": {"source": "indeed", "soft": True, "series": {
        "AK": s("Indeed job postings index, Alaska (Feb 1, 2020 = 100, seasonally adjusted)", "index", "monthly", "index"),
        "US": s("Indeed job postings index, United States (Feb 1, 2020 = 100, seasonally adjusted)", "index", "monthly", "index"),
    }},
    # JOLTS state job openings and LAUS unemployed persons, from the BLS API.
    # Openings per unemployed person = openings / unemployed.
    "job-openings": {"source": "bls", "soft": True, "series": {
        "JTS000000020000000JOL": s("Job openings, total nonfarm, Alaska (JOLTS, seasonally adjusted)", "thousands", "monthly", "level"),
        "JTS000000000000000JOL": s("Job openings, total nonfarm, United States (JOLTS, seasonally adjusted)", "thousands", "monthly", "level"),
        "LASST020000000000004": s("Unemployed persons, Alaska (seasonally adjusted)", "persons", "monthly", "level"),
        "LNS13000000": s("Unemployed persons, United States (seasonally adjusted)", "thousands", "monthly", "level"),
    }},
    "spending": {"source": "dolwd", "soft": True, "series": {
        "Total Nonfarm": s("Payroll jobs, total nonfarm", "jobs", "monthly", "level"),
        "Government": s("Payroll jobs, government", "jobs", "monthly", "level"),
        "Local Government": s("Payroll jobs, local government (incl. schools)", "jobs", "monthly", "level"),
        "State Government": s("Payroll jobs, state government", "jobs", "monthly", "level"),
        "Federal Government": s("Payroll jobs, federal government (civilian)", "jobs", "monthly", "level"),
    }},
}

SOURCE_NAMES = {
    "fred": "FRED, Federal Reserve Bank of St. Louis",
    "bls": "U.S. Bureau of Labor Statistics API",
    "eia": "U.S. Energy Information Administration, Electric Power Monthly (retail sales)",
    "eia_gas": "U.S. Energy Information Administration, Natural Gas Monthly (prices by state)",
    "census": "U.S. Census Bureau, County Business Patterns and Nonemployer Statistics (data API)",
    "bds": "U.S. Census Bureau, Business Dynamics Statistics (published CSV tables)",
    "dolwd": "Alaska Department of Labor and Workforce Development, Current Employment Statistics",
    "indeed": "Indeed Hiring Lab, job postings tracker (github.com/hiring-lab/job_postings_tracker, CC BY 4.0)",
}

# A soft dashboard (BLS without a key can be rate-limited) only fails the job
# once its data is this many days old.
SOFT_STALE_DAYS = 75


def note(level, msg):
    """Print a message GitHub shows as an annotation on the run."""
    print(f"::{level}::{msg}")


# ---------- FRED ----------

def parse_fred_csv(text):
    """Return (dates, values) from a FRED CSV, skipping missing values ('.')."""
    rows = list(csv.reader(io.StringIO(text)))
    dates, values = [], []
    for row in rows[1:]:
        if len(row) < 2 or row[1] in (".", ""):
            continue
        dates.append(row[0])
        values.append(float(row[1]))
    if not dates:
        raise ValueError("no data rows")
    return dates, values


def fetch_fred(series_id, tries=3):
    req = urllib.request.Request(FRED_CSV.format(series_id), headers=UA)
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                dates, values = parse_fred_csv(r.read().decode("utf-8"))
                return {"dates": dates, "values": values}
        except Exception as e:
            if attempt == tries - 1:
                raise RuntimeError(str(e)) from e
            time.sleep(5 * (attempt + 1))


# ---------- BLS ----------

def fetch_bls(series_ids, tries=3):
    """Return {series_id: {"dates", "values", "annual": {...}}} for the ids BLS knows.
    One request for up to 25 series (50 with a key). Ten years of history (20 with a key)."""
    key = os.environ.get("BLS_API_KEY", "").strip()
    end = date.today().year
    body = {"seriesid": list(series_ids), "startyear": str(end - (19 if key else 9)), "endyear": str(end)}
    if key:
        body.update(registrationkey=key, annualaverage=True)
    req = urllib.request.Request(BLS_V2 if key else BLS_V1, data=json.dumps(body).encode(),
                                 headers={**UA, "Content-Type": "application/json"})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                res = json.loads(r.read().decode("utf-8"))
            break
        except Exception as e:
            if attempt == tries - 1:
                raise RuntimeError(f"BLS request failed: {e}") from e
            time.sleep(10 * (attempt + 1))
    if res.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS: {res.get('status')} {' '.join(res.get('message', []))}"[:300])
    out = {}
    for ser in res.get("Results", {}).get("series", []):
        monthly, annual = {}, {}
        for obs in ser.get("data", []):
            try:
                v = float(obs["value"])
            except (ValueError, KeyError):
                continue  # '-' marks a missing value
            per = obs["period"]
            if per == "M13":
                annual[obs["year"]] = v
            elif per.startswith("M"):
                monthly[f"{obs['year']}-{per[1:]}-01"] = v
        if monthly:
            d = sorted(monthly)
            out[ser["seriesID"]] = {"dates": d, "values": [monthly[x] for x in d]}
            if annual:
                y = sorted(annual)
                out[ser["seriesID"]]["annual"] = {"dates": y, "values": [annual[x] for x in y]}
    return out


# ---------- EIA ----------

def fetch_eia(series_ids, tries=3):
    """Return {"<state>-<sector>": {"dates", "values"}} of monthly retail electricity
    prices (cents/kWh) from the EIA API v2, from 2001 on."""
    key = os.environ.get("EIA_API_KEY", "").strip()
    if not key:
        raise RuntimeError("EIA_API_KEY secret not set (free key: eia.gov/opendata/register.php)")
    wanted = [tuple(x.split(":")[0].split("-", 1)) for x in series_ids]
    params = [("api_key", key), ("frequency", "monthly"), ("data[0]", "price"), ("data[1]", "sales"), ("start", "2001-01"),
              ("sort[0][column]", "period"), ("sort[0][direction]", "asc"), ("length", "5000")]
    params += [("facets[stateid][]", st) for st in sorted({w[0] for w in wanted})]
    params += [("facets[sectorid][]", sec) for sec in sorted({w[1] for w in wanted})]
    url = EIA_RETAIL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                res = json.loads(r.read().decode("utf-8"))
            break
        except Exception as e:
            if attempt == tries - 1:
                # Don't echo the URL: it carries the key.
                raise RuntimeError(f"EIA request failed: {type(e).__name__}") from e
            time.sleep(10 * (attempt + 1))
    rows = (res.get("response") or {}).get("data") or []
    if not rows:
        raise RuntimeError(f"EIA returned no rows: {str(res.get('error') or res)[:200]}")
    found = {}
    for row in rows:
        base = f"{row.get('stateid')}-{row.get('sectorid')}"
        for field, sid in (("price", base), ("sales", base + ":sales")):
            try:
                v = float(row[field])
            except (TypeError, ValueError, KeyError):
                continue
            if sid in series_ids:
                found.setdefault(sid, {})[f"{row['period']}-01"] = v
    out = {}
    for sid, obs in found.items():
        d = sorted(obs)
        out[sid] = {"dates": d, "values": [obs[x] for x in d]}
    return out


GAS_TYPE = {"CITYGATE": "N3050", "RES": "N3010", "COM": "N3020", "IND": "N3035", "ELEC": "N3045"}


def fetch_eia_gas(series_ids, tries=3):
    """Return {"<area>-<type>": {"dates", "values"}} of monthly natural gas prices
    ($/Mcf) from the EIA API v2 (natural-gas/pri/sum), from 1997 on."""
    key = os.environ.get("EIA_API_KEY", "").strip()
    if not key:
        raise RuntimeError("EIA_API_KEY secret not set (free key: eia.gov/opendata/register.php)")
    eia_id = {}
    for sid in series_ids:
        area, kind = sid.split("-", 1)
        eia_id[f"{GAS_TYPE[kind]}{area}3"] = sid
    params = [("api_key", key), ("frequency", "monthly"), ("data[0]", "value"), ("start", "1997-01"),
              ("sort[0][column]", "period"), ("sort[0][direction]", "asc"), ("length", "5000")]
    params += [("facets[series][]", e) for e in sorted(eia_id)]
    req = urllib.request.Request(EIA_GAS + "?" + urllib.parse.urlencode(params), headers=UA)
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                res = json.loads(r.read().decode("utf-8"))
            break
        except Exception as e:
            if attempt == tries - 1:
                raise RuntimeError(f"EIA gas request failed: {type(e).__name__}") from e  # no URL: it has the key
            time.sleep(10 * (attempt + 1))
    rows = (res.get("response") or {}).get("data") or []
    if not rows:
        raise RuntimeError(f"EIA gas returned no rows: {str(res.get('error') or res)[:200]}")
    found = {}
    for row in rows:
        sid = eia_id.get(row.get("series"))
        try:
            v = float(row["value"])
        except (TypeError, ValueError, KeyError):
            continue  # withheld months come back empty
        if sid:
            found.setdefault(sid, {})[f"{row['period']}-01"] = v
    return {sid: {"dates": sorted(o), "values": [o[d] for d in sorted(o)]} for sid, o in found.items()}


# ---------- Census ----------

def census_vars(year):
    """The industry-code variable each Census year uses, newest scheme first."""
    if year >= 2022:
        return ["NAICS2022", "NAICS2017"]
    return ["NAICS2017"] if year >= 2017 else ["NAICS2012"]


def census_get(year, dataset, fields, geo, naics):
    """One Census API call. Returns {field: number} or None if the year/geo has no data."""
    key = os.environ.get("CENSUS_API_KEY", "").strip()
    for var in census_vars(year):
        params = [("get", ",".join(fields)), ("for", geo), (var, naics)]
        if key:
            params.append(("key", key))
        url = CENSUS_API.format(year=year, dataset=dataset) + "?" + urllib.parse.urlencode(params)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                body = r.read().decode("utf-8").strip()
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):   # wrong code variable for this year, or year not published
                continue
            note("warning", f"Census {dataset} {year} {geo}: HTTP {e.code}")
            return None
        except Exception as e:          # network trouble: skip this year, keep the rest
            note("warning", f"Census {dataset} {year} {geo}: {type(e).__name__}")
            return None
        if not body:                    # 204: no data for this geography/industry
            return None
        rows = json.loads(body)
        if len(rows) < 2:
            return None
        rec = dict(zip(rows[0], rows[1]))
        out = {}
        for f in fields:
            try:
                out[f] = float(rec.get(f))
            except (TypeError, ValueError):
                pass
        return out or None
    return None


def fetch_census(series_ids, naics):
    """Return {"<dataset>-<geo>:<field>": {"dates", "values"}} of annual counts,
    trying every year from 2012 to last year (unpublished years are skipped)."""
    geos = {"AK": "state:02", "US": "us:1"}
    want = {}
    for sid in series_ids:
        ds_geo, field = sid.split(":")
        ds, geo = ds_geo.split("-")
        want.setdefault((ds, geo), []).append(field)
    found = {}
    for (ds, geo), fields in want.items():
        for year in range(2012, date.today().year):
            got = census_get(year, ds, fields, geos[geo], naics)
            time.sleep(0.3)
            for f, v in (got or {}).items():
                found.setdefault(f"{ds}-{geo}:{f}", {})[f"{year}-01-01"] = v
    out = {}
    for sid, obs in found.items():
        d = sorted(obs)
        # County Business Patterns reports 0 when a value is withheld; drop those.
        vals = [obs[x] for x in d]
        keep = [i for i, v in enumerate(vals) if v > 0]
        if keep:
            out[sid] = {"dates": [d[i] for i in keep], "values": [vals[i] for i in keep]}
    return out


# ---------- Census Business Dynamics Statistics ----------

BDS_URL = "https://www2.census.gov/programs-surveys/bds/tables/time-series/{v}/bds{v}{tab}.csv"


def bds_table(tab, tries=2):
    """Rows of one BDS table (tab: '' economy-wide, '_st' by state, '_fa' by firm age, ...),
    from the newest vintage published. Returns (vintage, rows)."""
    for v in range(date.today().year - 1, 2021, -1):
        url = BDS_URL.format(v=v, tab=tab)
        for attempt in range(tries):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
                    text = r.read().decode("utf-8-sig", errors="replace")
                rows = [{k.strip().lower(): (x or "").strip() for k, x in row.items() if k} for row in csv.DictReader(io.StringIO(text))]
                if rows:
                    need = {"year", "firms", "emp"} | ({"st"} if "_st" in tab else set()) | ({"fage"} if "fa" in tab else set()) | ({"sector"} if "sec" in tab else set())
                    if not need <= set(rows[0]):
                        raise ValueError(f"BDS bds{v}{tab}.csv columns changed; has {sorted(rows[0])[:25]}")
                    return v, rows
                break
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    break               # this vintage isn't out yet; try the one before
                if attempt == tries - 1:
                    raise RuntimeError(f"BDS {url}: HTTP {e.code}") from e
            except Exception as e:
                if attempt == tries - 1:
                    raise RuntimeError(f"BDS {url}: {type(e).__name__}: {e}") from e
            time.sleep(5)
    raise RuntimeError(f"BDS table bds<vintage>{tab}.csv not found for any vintage")


def num(x):
    """BDS marks withheld cells with letters (D, S, X, N); those come back None."""
    try:
        return float(x.replace(",", ""))
    except (AttributeError, ValueError):
        return None


def is_ak(row):
    return row.get("st", "").lstrip("0") == "2"


def fetch_bds(series_ids):
    """Firm entry, exit and establishment entry for Alaska and the U.S.
    Entry rate = age-0 firms / all firms (the BDS 'startup rate'); exit rate =
    firm deaths / all firms; establishment entry rate as published."""
    acc = {}                                # sid -> {year: value}

    def put(sid, year, v):
        if v is not None and sid in series_ids:
            acc.setdefault(sid, {})[f"{int(year)}-01-01"] = v

    totals = {}                             # (geo, year) -> row
    vint, us = bds_table("")
    _, st = bds_table("_st")
    for geo, rows in (("US", us), ("AK", [r for r in st if is_ak(r)])):
        for r in rows:
            totals[(geo, r["year"])] = r
            put(f"FIRMS-{geo}", r["year"], num(r.get("firms")))
            put(f"ESTAB_ENTRY_RATE-{geo}", r["year"], num(r.get("estabs_entry_rate")))
            f, d = num(r.get("firms")), num(r.get("firmdeath_firms"))
            if f and d is not None:
                put(f"FIRM_EXIT_RATE-{geo}", r["year"], 100 * d / f)

    _, us_fa = bds_table("_fa")
    _, st_fa = bds_table("_st_fa")
    for geo, rows in (("US", us_fa), ("AK", [r for r in st_fa if is_ak(r)])):
        young = {}
        for r in rows:
            age = r.get("fage", "").lower()
            y = r["year"]
            emp = num(r.get("emp"))
            if age[:2] in ("a)", "b)", "c)", "d)", "e)", "f)"):   # ages 0 through 5
                young.setdefault(y, []).append(emp)
            if not age.startswith("a)"):
                continue
            tot = totals.get((geo, y), {})
            firms, all_firms, all_emp = num(r.get("firms")), num(tot.get("firms")), num(tot.get("emp"))
            put(f"STARTUPS-{geo}", y, firms)
            put(f"STARTUP_EMP-{geo}", y, emp)
            if firms is not None and all_firms:
                put(f"FIRM_ENTRY_RATE-{geo}", y, 100 * firms / all_firms)
            if emp is not None and all_emp:
                put(f"STARTUP_EMP_SHARE-{geo}", y, 100 * emp / all_emp)
        for y, vals in young.items():
            all_emp = num(totals.get((geo, y), {}).get("emp"))
            if len(vals) == 6 and None not in vals and all_emp:
                put(f"YOUNG_EMP_SHARE-{geo}", y, 100 * sum(vals) / all_emp)

    _, us_sec = bds_table("_sec")
    _, st_sec = bds_table("_st_sec")
    for geo, rows in (("US", us_sec), ("AK", [r for r in st_sec if is_ak(r)])):
        for r in rows:
            code = r.get("sector", "")
            put(f"SEC{code}:ESTAB_ENTRY_RATE-{geo}", r["year"], num(r.get("estabs_entry_rate")))
            put(f"SEC{code}:ESTABS-{geo}", r["year"], num(r.get("estabs")))

    print(f"  BDS vintage {vint}")
    return {sid: {"dates": sorted(o), "values": [o[d] for d in sorted(o)], "vintage": vint} for sid, o in acc.items()}


# ---------- Alaska DOLWD ----------

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december"]


def fetch_dolwd(names, tries=3):
    """Return {industry name: {"dates", "values"}} from DOLWD's statewide payroll CSV."""
    req = urllib.request.Request(DOLWD_CES, headers=UA)
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                text = r.read().decode("utf-8-sig", errors="replace")
            break
        except Exception as e:
            if attempt == tries - 1:
                raise RuntimeError(f"DOLWD CSV: {e}") from e
            time.sleep(10 * (attempt + 1))
    # The file opens with a title line ("Alaska Monthly Employment Statistics") before the header.
    start = text.find("areaname,")
    found = {}
    reader = csv.DictReader(io.StringIO(text[start:] if start >= 0 else text))
    for raw in reader:
        # Rows can carry trailing commas; csv puts those extras under a None key as a list.
        row = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if isinstance(k, str) and not isinstance(v, list)}
        name = row.get("industry", "")
        if name not in names or row.get("adjusted", "0") not in ("0", ""):
            continue
        year = row.get("year", "")
        for i, m in enumerate(MONTHS):
            v = row.get(f"emp_{m}", "").replace(",", "")
            if v:
                found.setdefault(name, {})[f"{year}-{i + 1:02d}-01"] = float(v)
    if not found:
        snippet = " ".join(text[:300].split())
        raise RuntimeError(f"DOLWD CSV had none of the expected rows; it began: {snippet!r}")
    out = {}
    for name, obs in found.items():
        d = sorted(obs)
        out[name] = {"dates": d, "values": [obs[x] for x in d]}
    return out


# ---------- Indeed Hiring Lab ----------

INDEED_STATE = "https://raw.githubusercontent.com/hiring-lab/job_postings_tracker/master/US/state_job_postings_us.csv"
INDEED_US = "https://raw.githubusercontent.com/hiring-lab/job_postings_tracker/master/US/aggregate_job_postings_US.csv"


def fetch_indeed(wanted, tries=3):
    """Monthly averages of Indeed's daily postings index for Alaska and the U.S."""
    def grab(url):
        for attempt in range(tries):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90) as r:
                    return list(csv.DictReader(io.StringIO(r.read().decode("utf-8"))))
            except Exception as e:
                if attempt == tries - 1:
                    raise RuntimeError(f"Indeed CSV: {e}") from e
                time.sleep(5 * (attempt + 1))

    def monthly(pairs):
        by = {}
        for d, v in pairs:
            by.setdefault(d[:7] + "-01", []).append(v)
        ds = sorted(by)
        return {"dates": ds, "values": [round(sum(by[x]) / len(by[x]), 2) for x in ds],
                "last_day": max(d for d, _ in pairs)}

    out = {}
    if "AK" in wanted:
        rows = grab(INDEED_STATE)
        pairs = [(r["date"], float(r["indeed_job_postings_index"])) for r in rows
                 if r.get("state", "").lower() == "ak" and r.get("indeed_job_postings_index")]
        if pairs:
            out["AK"] = monthly(pairs)
    if "US" in wanted:
        rows = grab(INDEED_US)
        pairs = [(r["date"], float(r["indeed_job_postings_index_SA"])) for r in rows
                 if r.get("variable") == "total postings" and r.get("indeed_job_postings_index_SA")]
        if pairs:
            out["US"] = monthly(pairs)
    return out


# ---------- build / write ----------

def build(slug, cfg):
    """Fetch one dashboard. Returns (data, problems) where problems lists
    (series_id, message, optional)."""
    out = {
        "dashboard": slug,
        "source": SOURCE_NAMES[cfg["source"]],
        "fetched": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "series": {},
    }
    problems = []
    meta = cfg["series"]
    if cfg["source"] == "bls":
        got = fetch_bls(meta.keys())
    elif cfg["source"] == "dolwd":
        got = fetch_dolwd(set(meta))
    elif cfg["source"] == "eia":
        got = fetch_eia(set(meta))
    elif cfg["source"] == "eia_gas":
        got = fetch_eia_gas(set(meta))
    elif cfg["source"] == "census":
        got = fetch_census(set(meta), cfg["naics"])
    elif cfg["source"] == "bds":
        got = fetch_bds(set(meta))
    elif cfg["source"] == "indeed":
        got = fetch_indeed(set(meta))
    else:
        got = {}
        for sid, m in meta.items():
            try:
                got[sid] = fetch_fred(sid)
            except Exception as e:
                problems.append((sid, str(e), m["optional"]))
    for sid, m in meta.items():
        if sid not in got:
            if not any(p[0] == sid for p in problems):
                problems.append((sid, "not returned by the source", m["optional"]))
            continue
        entry = {k: v for k, v in m.items() if k != "optional"}
        entry.update(got[sid])
        out["series"][sid] = entry
        print(f"  {sid}: {len(entry['values'])} obs, latest {entry['dates'][-1]} = {entry['values'][-1]:,.3f}")
    return out, problems


def write_if_changed(slug, data):
    """Only rewrite the file when the numbers changed, so the workflow
    doesn't commit every run just because the fetch date moved."""
    path = DATA_DIR / f"{slug}.json"
    if path.exists():
        old = json.loads(path.read_text())
        if old.get("series") == data["series"]:
            print(f"  {slug}: no new data")
            return False
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1) + "\n")
    print(f"  {slug}: updated {path.name}")
    return True


def age_days(slug):
    path = DATA_DIR / f"{slug}.json"
    if not path.exists():
        return None
    fetched = json.loads(path.read_text()).get("fetched")
    try:
        return (date.today() - date.fromisoformat(fetched)).days
    except (TypeError, ValueError):
        return None


def update_status(results):
    """site/data/status.json: what each dashboard has and any problems.
    No timestamps of the run itself, so it only changes when something real does."""
    path = DATA_DIR / "status.json"
    status = json.loads(path.read_text()) if path.exists() else {}
    for slug, info in results.items():
        status[slug] = info
    path.write_text(json.dumps(dict(sorted(status.items())), indent=1) + "\n")


def main(argv):
    wanted = argv or list(DASHBOARDS)
    failed, results = [], {}
    for slug in wanted:
        cfg = DASHBOARDS[slug]
        print(slug)
        if cfg["source"].startswith("eia") and not os.environ.get("EIA_API_KEY", "").strip():
            note("warning", f"{slug}: skipped, EIA_API_KEY secret not set")
            continue
        try:
            data, problems = build(slug, cfg)
        except Exception as e:
            data, problems = None, [("*", str(e), False)]
        hard = [p for p in problems if not p[2]]
        for sid, msg, opt in problems:
            note("warning" if opt else "error", f"{slug} {sid}: {msg}")
        if data and data["series"] and not hard:
            write_if_changed(slug, data)
        # If a required series is missing, keep the old file rather than publish a partial one.
        info = {
            "source": cfg["source"],
            "latest": {sid: v["dates"][-1] for sid, v in (data or {}).get("series", {}).items()},
            "problems": [f"{sid}: {msg}" + (" (optional)" if opt else "") for sid, msg, opt in problems],
        }
        if hard:
            if cfg.get("soft"):
                age = age_days(slug)
                if age is not None and age <= SOFT_STALE_DAYS:
                    note("warning", f"{slug}: kept data from {age} days ago")
                    info["problems"].append(f"kept existing data ({age} days old)")
                else:
                    failed.append(slug)
            else:
                failed.append(slug)
        if not info["problems"]:
            del info["problems"]
        results[slug] = info
    update_status(results)
    if failed:
        sys.exit(f"Failed: {', '.join(failed)}")


if __name__ == "__main__":
    main(sys.argv[1:])
