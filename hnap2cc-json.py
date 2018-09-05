#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Usage: hnap2cc-json.py [-e Error file to generate]

Convert HNAP 2.3.1 XML from FGP platform CSW v1.6.2 to OGP Portal input

Accepts streamed HNAP xml input or a supplied HNAP xml filename

    cat hnap.xml | hnap2cc-json.py [-e Error file to generate]
    hnap2cc-json.py [-e Error file to generate] hnap.xml

Options:
    -e Error file to generate
"""

##################################################
# Schema import
import csv
# FGP XML Parsing
from lxml import etree
# CKAN food export
import json
# Date validation
import datetime

import urllib2
from urlparse import urlparse

import sys
from io import StringIO, BytesIO
import time
import re
import codecs

import unicodedata

import docopt

MIN_TAG_LENGTH = 2
MAX_TAG_LENGTH = 140

##################################################
# TL err/dbg
error_output = []
error_records = {}

##################################################
# Process the command request

# #Default import location
# input_file     = 'data/majechr_source.xml'
# input_file     = 'data/hnap_import.xml'
input_file = None

# Use stdin if it's populated
if not sys.stdin.isatty():
    input_file = BytesIO(sys.stdin.read())

# Otherwise, read for a given filename
if len(sys.argv) == 2:
    input_file = sys.argv[1]

if input_file is None:
    sys.stdout.write("""
Either stream HNAP in or supply a file
> cat hnap.xml | ./hnap2json.py
> ./hnap2json.py hnap.xml
""")
    sys.exit()

##################################################
# Input can be multiple XML blocks
# Ensure to never try to be clever only taking the
# last XML record or reduce or sort or try to
# combine them.  Each of these updates need to
# happen in the order they were supplied to ensure
# the order of changes.
# We can also not reprocess parts without all the
# subsequent records.  You can't re-process data
# from a particular span of time, any historical
# re-procssing must continue to the current day.
input_data_blocks = []
active_input_block = ''
for line in input_file:
    if not line.strip():
        continue
    if active_input_block == '':
        active_input_block += line
    elif re.search(r'^<\?xml', line):
        input_data_blocks.append(active_input_block)
        active_input_block = line
    else:
        active_input_block += line
input_data_blocks.append(active_input_block)

##################################################
# Extract the schema to convert to
schema_file = 'config/Schema--GC.OGS.TBS-CommonCore-OpenMaps.csv'
schema_ref = {}
with open(schema_file, 'rb') as f:
    reader = csv.reader(f)
    for row in reader:
        if row[0] == 'Property ID':
            continue
        schema_ref[row[0]] = {}
        schema_ref[row[0]]['Property ID'] = row[0]
        schema_ref[row[0]]['CKAN API property'] = row[1]
        schema_ref[row[0]]['Schema Name English'] = unicode(row[2], 'utf-8')
        schema_ref[row[0]]['Schema Name French'] = unicode(row[3], 'utf-8')
        schema_ref[row[0]]['Requirement'] = row[4]
        schema_ref[row[0]]['Occurrences'] = row[5]
        schema_ref[row[0]]['Reference'] = row[6]
        schema_ref[row[0]]['Value Type'] = row[7]
        schema_ref[row[0]]['FGP XPATH'] = unicode(row[8], 'utf-8')
        schema_ref[row[0]]['RegEx Filter'] = unicode(row[9], 'utf-8')


records_root = ("/csw:GetRecordsResponse/"
                "csw:SearchResults/"
                "gmd:MD_Metadata")

source_hnap = ("csw.open.canada.ca/geonetwork/srv/"
               "csw?service=CSW"
               "&version=2.0.2"
               "&request=GetRecordById"
               "&outputSchema=csw:IsoRecord"
               "&id=")

mappable_protocols = [
    "OGC:WMS",
    "ESRI REST: Map Service",
    "ESRI REST: Feature Service",
    "ESRI REST: Image Service",
    "ESRI REST: Tiled Map Service",
    "WMS de l'OGC",
    "REST de L'ESRI : Service de cartes",
    "REST de L'ESRI : Service d’entités géographiques",
    "REST de L'ESRI : Service d’imagerie",
    "REST de L'ESRI : Service de pavés cartographiques"
]

iso_time = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())

def main():
    output_jl = "harvested_records.jl"
    output_err = "harvested_record_errors.csv"
    num_rejects = 0
    num_view_on_map = 0

    # Is there a specified start date
    if arguments['-e']:
        output_err = arguments['-e']

    json_records = []
    for input_block in input_data_blocks:
        if not input_block:
            continue

        # Read the file, should be a streamed input in the future
        root = etree.XML(input_block)
        # Parse the root and iterate over each record
        records = fetchXMLArray(root, records_root)

        for record in records:
            json_record = {}

            can_be_used_in_RAMP = False
            json_record['display_flags'] = []

##################################################
# HNAP CORE LANGUAGE
##################################################
# Language is required, the rest can't be processed
# for errors if the primary language is not certain

            tmp = fetchXMLValues(record, schema_ref["12"]['FGP XPATH'])
            if sanitySingle('NOID', ['HNAP Priamry Language'], tmp) is False:
                HNAP_primary_language = False
            else:
                HNAP_primary_language = sanityFirst(tmp).split(';')[0].strip()
                if HNAP_primary_language == 'eng':
                    CKAN_primary_lang = 'en'
                    CKAN_secondary_lang = 'fr'
                    HNAP_primary_lang = 'English'
                    HNAP_secondary_lang = 'French'
                else:
                    CKAN_primary_lang = 'fr'
                    CKAN_secondary_lang = 'en'
                    HNAP_primary_lang = 'French'
                    HNAP_secondary_lang = 'English'

##################################################
# Catalogue Metadata
##################################################

# CC::OpenMaps-01 Catalogue Type
            json_record[schema_ref["01"]['CKAN API property']] = 'dataset'
# CC::OpenMaps-02 Collection Type
            json_record[schema_ref["02"]['CKAN API property']] = 'fgp'
# CC::OpenMaps-03 Metadata Scheme
#       CKAN defined/provided
# CC::OpenMaps-04 Metadata Scheme Version
#       CKAN defined/provided
# CC::OpenMaps-05 Metadata Record Identifier
            tmp = fetchXMLValues(record, schema_ref["05"]['FGP XPATH'])
            if sanitySingle('NOID', ['fileIdentifier'], tmp) is False:
                HNAP_fileIdentifier = False
            else:
                json_record[schema_ref["05"]['CKAN API property']] =\
                    HNAP_fileIdentifier =\
                    sanityFirst(tmp)

##################################################
# Point of no return
# fail out if you don't have either a primary language or ID
##################################################

            if HNAP_primary_language is False or HNAP_fileIdentifier is False:
                break

# From here on in continue if you can and collect as many errors as
# possible for FGP Help desk.  We awant to have a full report of issues
# to correct, not piecemeal errors.
# It's faster for them to correct a batch of errors in parallel as
# opposed to doing them piecemeal.

# CC::OpenMaps-06 Metadata Contact (English)
            primary_vals = []
            # organizationName
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["06a"])
            if value:
                for single_value in value:
                    primary_vals.append(single_value)
            # voice
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["06b"])
            if value:
                for single_value in value:
                    primary_vals.append(single_value)
            # electronicMailAddress
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["06c"])
            if value:
                for single_value in value:
                    primary_vals.append(single_value)

            json_record[schema_ref["06"]['CKAN API property']] = {}
            json_record[
                schema_ref["06"]['CKAN API property']
            ][CKAN_primary_lang] = ','.join(primary_vals)

# CC::OpenMaps-07 Metadata Contact (French)
            second_vals = []

            # organizationName
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["07a"])
            if value:
                for single_value in value:
                    second_vals.append(single_value)
            # voice
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["07b"])
            if value:
                for single_value in value:
                    primary_vals.append(single_value)
            # electronicMailAddress
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["07c"])
            if value:
                for single_value in value:
                    second_vals.append(single_value)

            json_record[
                schema_ref["06"]['CKAN API property']
            ][CKAN_secondary_lang] = ','.join(second_vals)

# CC::OpenMaps-08 Source Metadata Record Date Stamp
            tmp = fetchXMLValues(record, schema_ref["08a"]['FGP XPATH'])
            values = list(set(tmp))
            if len(values) < 1:
                tmp = fetchXMLValues(record, schema_ref["08b"]['FGP XPATH'])

            if sanityMandatory(
                HNAP_fileIdentifier,
                [schema_ref["08"]['CKAN API property']],
                tmp
            ):
                if sanitySingle(
                    HNAP_fileIdentifier,
                    [schema_ref["08"]['CKAN API property']],
                    tmp
                ):
                    # Might be a iso datetime
                    date_str = sanityFirst(tmp)
                    if date_str.count('T') == 1:
                        date_str = date_str.split('T')[0]

                    if sanityDate(
                            HNAP_fileIdentifier,
                            [schema_ref["08"]['CKAN API property']],
                            date_str):
                        json_record[schema_ref["08"]['CKAN API property']] =\
                            date_str

# CC::OpenMaps-09 Metadata Contact (French)

            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["09"])
            if value:
                json_record[schema_ref["09"]['CKAN API property']] = value

# CC::OpenMaps-10 Parent identifier

            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["10"])
            if value:
                json_record[schema_ref["10"]['CKAN API property']] = value

# CC::OpenMaps-11 Hierarchy level

            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["11"])
            if value:
                json_record[schema_ref["11"]['CKAN API property']] = value

# CC::OpenMaps-12 File Identifier

            json_record[schema_ref["12"]['CKAN API property']] =\
                HNAP_fileIdentifier

# CC::OpenMaps-13 Short Key

            # Disabled as per the current install of RAMP
            # json_record[schema_ref["13"]
            # ['CKAN API property']] = HNAP_fileIdentifier[0:8]

# CC::OpenMaps-14 Title (English)
            json_record[schema_ref["14"]['CKAN API property']] = {}
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["14"])
            if value:
                json_record[
                    schema_ref["14"]['CKAN API property']
                ][CKAN_primary_lang] = value
# CC::OpenMaps-15 Title (French)
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["15"])
            if value:
                json_record[
                    schema_ref["14"]['CKAN API property']
                ][CKAN_secondary_lang] = value

# CC::OpenMaps-16 Publisher - Current Organization Name

            org_strings = []
            org_string = ''
            attempt = ''

            if HNAP_primary_lang == 'English':
                primary_lang_search_string = "^Government of Canada;"
                secondary_lang_search_string = "^Government du Canada;"
            else:
                primary_lang_search_string = "^Government du Canada;"
                secondary_lang_search_string = "^Government of Canada;"

            value = fetch_FGP_value(
                record, HNAP_fileIdentifier, schema_ref["16a"])
            if not value or len(value) < 1:
                attempt += "No primary language value"
            else:
                attempt += "Has primary language value ["+str(len(value))+"]"
                for single_value in value:
                    if re.search(primary_lang_search_string, single_value):
                        org_strings.append(single_value)
                    else:
                        attempt += " but no GoC/GdC prefix ["+single_value+"]"

            value = fetch_FGP_value(
                record, HNAP_fileIdentifier, schema_ref["16b"])
            if not value or len(value) < 1:
                attempt += ", no secondary language value"
            else:
                attempt += ", secondary language ["+str(len(value))+"]"
                for single_value in value:
                    if re.search(secondary_lang_search_string, single_value):
                        org_strings.append(single_value)
                    else:
                        attempt += " but no GoC/GdC ["+single_value+"]"

            if len(org_strings) < 1:
                reportError(
                    HNAP_fileIdentifier, [
                        schema_ref["16"]['CKAN API property'],
                        "Bad organizationName, no Government of Canada",
                        attempt
                    ])
            else:
                valid_orgs = []
                for org_string in org_strings:
                    GOC_Structure = org_string.strip().split(';')
                    del GOC_Structure[0]

                    # Append to contributor
                    contributor_english = []
                    contributor_french = []

                    # At ths point you have ditched GOC and your checking for good
                    # dept names
                    for GOC_Div in GOC_Structure:
                        # Are they in the CL?
                        termsValue = fetchCLValue(
                            GOC_Div, GC_Registry_of_Applied_Terms)
                        if termsValue:
                            contributor_english.append(termsValue[0])
                            contributor_french.append(termsValue[2])
                            if termsValue[1] == termsValue[3]:
                                valid_orgs.append(termsValue[1].lower())
                            else:
                                valid_orgs.append((termsValue[1]+"-"+termsValue[3]).lower())
                            break

                # Unique the departments, don't need duplicates
                valid_orgs = list(set(valid_orgs))

                if len(valid_orgs) < 1:
                    reportError(
                        HNAP_fileIdentifier, [
                            schema_ref["16"]['CKAN API property'],
                            "No valid orgs found",
                            org_string.strip()
                        ])
                else:
                    json_record[schema_ref["16"]['CKAN API property']] = valid_orgs[0]

                # Unique the departments, don't need duplicates
                contributor_english = list(set(contributor_english))
                contributor_french = list(set(contributor_french))

                # Multiple owners, excess pushed to contrib
                if len(valid_orgs) > 1:
                    del valid_orgs[0]
                    del contributor_english[0]
                    del contributor_french[0]
                    json_record[schema_ref["22"]['CKAN API property']] = {}
                    json_record[schema_ref["22"]['CKAN API property']]['en'] = []
                    json_record[schema_ref["22"]['CKAN API property']]['fr'] = []
                    for org in valid_orgs:
                        json_record[schema_ref["22"]['CKAN API property']]['en'] = ','.join(contributor_english)
                        json_record[schema_ref["22"]['CKAN API property']]['fr'] = ','.join(contributor_french)

# CC::OpenMaps-17 Publisher - Organization Name at Publication (English)
#       CKAN defined/provided
# CC::OpenMaps-18 Publisher - Organization Name at Publication (French)
#       CKAN defined/provided
# CC::OpenMaps-19 Publisher - Organization Section Name (English)
#       CKAN defined/provided
# CC::OpenMaps-20 Publisher - Organization Section Name (French)
#       CKAN defined/provided

# CC::OpenMaps-21 Creator

            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["21"])
            if value:
                json_record[schema_ref["21"]['CKAN API property']] = ','.join(value)

# CC::OpenMaps-22 Contributor (English)
#       Intentionally left blank, assuming singular contribution
# CC::OpenMaps-23 Contributor (French)
#       Intentionally left blank, assuming singular contribution

# CC::OpenMaps-24 Position Name (English)
# CC::OpenMaps-25 Position Name (French)

            json_record[schema_ref["24"]['CKAN API property']] = {}

            schema_ref["24"]['Occurrences'] = 'R'
            primary_data = []
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["24"])
            if value:
                for single_value in value:
                    primary_data.append(value)

            if len(primary_data) > 0:
                json_record[schema_ref["24"]['CKAN API property']][CKAN_primary_lang] = ','.join(value)

            schema_ref["25"]['Occurrences'] = 'R'
            primary_data = []
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["25"])
            if value:
                for single_value in value:
                    primary_data.append(value)

            if len(primary_data) > 0:
                json_record[schema_ref["24"]['CKAN API property']][CKAN_secondary_lang] = ','.join(value)

            if len(json_record[schema_ref["24"]['CKAN API property']]) < 1:
                del json_record[schema_ref["24"]['CKAN API property']]

# CC::OpenMaps-26 Role

            # Single report out, multiple records combined
            schema_ref["26"]['Occurrences'] = 'R'
            primary_data = []
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["26"])
            if value:
                for single_value in value:
                    # Can you find the CL entry?
                    termsValue = fetchCLValue(single_value, napCI_RoleCode)
                    if not termsValue:
                        reportError(
                            HNAP_fileIdentifier, [
                                schema_ref["26"]['CKAN API property'],
                                'Value not found in '+schema_ref["26"]['Reference']
                            ])
                    else:
                        primary_data.append(termsValue[0])

            if len(primary_data) > 0:
                json_record[schema_ref["26"]['CKAN API property']] = ','.join(value)

# CC::OpenMaps-27
#       Undefined property number
# CC::OpenMaps-28
#       Undefined property number

# CC::OpenMaps-29 Contact Information (English)

            primary_vals = {}
            primary_vals[CKAN_primary_lang] = {}

            # HACK - find out of there is a pointOfContact role provided
            ref = schema_ref["29a"]["FGP XPATH"].split("gmd:CI_ResponsibleParty")[0] + "gmd:CI_ResponsibleParty[gmd:role/gmd:CI_RoleCode[@codeListValue='RI_414']]"
            tmp = fetchXMLValues(record, ref)
            xpath_sub = ""

            if len(tmp) > 0:
                xpath_sub = "gmd:CI_ResponsibleParty[gmd:role/gmd:CI_RoleCode[@codeListValue='RI_414']]"

            # deliveryPoint
            # value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["29a"])
            value = fetch_FGP_value(record, HNAP_fileIdentifier, {"Requirement": schema_ref["29a"]['Requirement'], "Occurrences": schema_ref["29a"]['Occurrences'],"FGP XPATH": schema_ref["29a"]["FGP XPATH"].replace("gmd:CI_ResponsibleParty", xpath_sub), "Value Type": schema_ref["29a"]['Value Type'], "CKAN API property": schema_ref["29a"]['CKAN API property']})

            if value:
                for single_value in value:
                    primary_vals[CKAN_primary_lang]['delivery_point'] = single_value
            # city
            # value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["29b"])
            value = fetch_FGP_value(record, HNAP_fileIdentifier, {"Requirement": schema_ref["29b"]['Requirement'], "Occurrences": schema_ref["29b"]['Occurrences'],"FGP XPATH": schema_ref["29b"]["FGP XPATH"].replace("gmd:CI_ResponsibleParty", xpath_sub), "Value Type": schema_ref["29b"]['Value Type'], "CKAN API property": schema_ref["29b"]['CKAN API property']})

            if value:
                for single_value in value:
                    primary_vals[CKAN_primary_lang]['city'] = single_value
            # administrativeArea
            # value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["29c"])
            value = fetch_FGP_value(record, HNAP_fileIdentifier, {"Requirement": schema_ref["29c"]['Requirement'], "Occurrences": schema_ref["29c"]['Occurrences'],"FGP XPATH": schema_ref["29c"]["FGP XPATH"].replace("gmd:CI_ResponsibleParty", xpath_sub), "Value Type": schema_ref["29c"]['Value Type'], "CKAN API property": schema_ref["29c"]['CKAN API property']})

            if value:
                for single_value in value:
                    primary_vals[CKAN_primary_lang]['administrative_area'] = single_value
            # postalCode
            # value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["29d"])
            value = fetch_FGP_value(record, HNAP_fileIdentifier, {"Requirement": schema_ref["29d"]['Requirement'], "Occurrences": schema_ref["29d"]['Occurrences'],"FGP XPATH": schema_ref["29d"]["FGP XPATH"].replace("gmd:CI_ResponsibleParty", xpath_sub), "Value Type": schema_ref["29d"]['Value Type'], "CKAN API property": schema_ref["29d"]['CKAN API property']})

            if value:
                for single_value in value:
                    primary_vals[CKAN_primary_lang]['postal_code'] = single_value
            # country
            # value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["29e"])
            value = fetch_FGP_value(record, HNAP_fileIdentifier, {"Requirement": schema_ref["29e"]['Requirement'], "Occurrences": schema_ref["29e"]['Occurrences'],"FGP XPATH": schema_ref["29e"]["FGP XPATH"].replace("gmd:CI_ResponsibleParty", xpath_sub), "Value Type": schema_ref["29e"]['Value Type'], "CKAN API property": schema_ref["29e"]['CKAN API property']})

            if value:
                for single_value in value:
                    primary_vals[CKAN_primary_lang]['country'] = single_value
            # electronicMailAddress
            # value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["29f"])
            value = fetch_FGP_value(record, HNAP_fileIdentifier, {"Requirement": schema_ref["29f"]['Requirement'], "Occurrences": schema_ref["29f"]['Occurrences'],"FGP XPATH": schema_ref["29f"]["FGP XPATH"].replace("gmd:CI_ResponsibleParty", xpath_sub), "Value Type": schema_ref["29f"]['Value Type'], "CKAN API property": schema_ref["29f"]['CKAN API property']})

            if value:
                for single_value in value:
                    primary_vals[CKAN_primary_lang]['electronic_mail_address'] = single_value

            if len(primary_vals[CKAN_primary_lang]) < 1:
                reportError(
                    HNAP_fileIdentifier, [
                        schema_ref["29"]['CKAN API property'],
                        'Value not found in '+schema_ref["29"]['Reference']
                    ])

# CC::OpenMaps-30 Contact Information (French)

            primary_vals[CKAN_secondary_lang] = {}

            # deliveryPoint
            # value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["30a"])
            value = fetch_FGP_value(record, HNAP_fileIdentifier, {"Requirement": schema_ref["30a"]['Requirement'], "Occurrences": schema_ref["30a"]['Occurrences'],"FGP XPATH": schema_ref["30a"]["FGP XPATH"].replace("gmd:CI_ResponsibleParty", xpath_sub), "Value Type": schema_ref["30a"]['Value Type'], "CKAN API property": schema_ref["30a"]['CKAN API property']})

            if value:
                for single_value in value:
                    primary_vals[CKAN_secondary_lang]['delivery_point'] = single_value
            # city
            # value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["30b"])
            value = fetch_FGP_value(record, HNAP_fileIdentifier, {"Requirement": schema_ref["30b"]['Requirement'], "Occurrences": schema_ref["30b"]['Occurrences'],"FGP XPATH": schema_ref["30b"]["FGP XPATH"].replace("gmd:CI_ResponsibleParty", xpath_sub), "Value Type": schema_ref["30b"]['Value Type'], "CKAN API property": schema_ref["30b"]['CKAN API property']})

            if value:
                for single_value in value:
                    primary_vals[CKAN_secondary_lang]['city'] = single_value
            # administrativeArea
            # value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["30c"])
            value = fetch_FGP_value(record, HNAP_fileIdentifier, {"Requirement": schema_ref["30c"]['Requirement'], "Occurrences": schema_ref["30c"]['Occurrences'],"FGP XPATH": schema_ref["30c"]["FGP XPATH"].replace("gmd:CI_ResponsibleParty", xpath_sub), "Value Type": schema_ref["30c"]['Value Type'], "CKAN API property": schema_ref["30c"]['CKAN API property']})

            if value:
                for single_value in value:
                    primary_vals[CKAN_secondary_lang]['administrative_area'] = single_value
            # postalCode
            # value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["30d"])
            value = fetch_FGP_value(record, HNAP_fileIdentifier, {"Requirement": schema_ref["30d"]['Requirement'], "Occurrences": schema_ref["30d"]['Occurrences'],"FGP XPATH": schema_ref["30d"]["FGP XPATH"].replace("gmd:CI_ResponsibleParty", xpath_sub), "Value Type": schema_ref["30d"]['Value Type'], "CKAN API property": schema_ref["30d"]['CKAN API property']})

            if value:
                for single_value in value:
                    primary_vals[CKAN_secondary_lang]['postal_code'] = single_value
            # country
            # value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["30e"])
            value = fetch_FGP_value(record, HNAP_fileIdentifier, {"Requirement": schema_ref["30e"]['Requirement'], "Occurrences": schema_ref["30e"]['Occurrences'],"FGP XPATH": schema_ref["30e"]["FGP XPATH"].replace("gmd:CI_ResponsibleParty", xpath_sub), "Value Type": schema_ref["30e"]['Value Type'], "CKAN API property": schema_ref["30e"]['CKAN API property']})

            if value:
                for single_value in value:
                    primary_vals[CKAN_secondary_lang]['country'] = single_value
            # electronicMailAddress
            # value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["30f"])
            value = fetch_FGP_value(record, HNAP_fileIdentifier, {"Requirement": schema_ref["30f"]['Requirement'], "Occurrences": schema_ref["30f"]['Occurrences'],"FGP XPATH": schema_ref["30f"]["FGP XPATH"].replace("gmd:CI_ResponsibleParty", xpath_sub), "Value Type": schema_ref["30f"]['Value Type'], "CKAN API property": schema_ref["30f"]['CKAN API property']})
            
            if value:
                for single_value in value:
                    primary_vals[CKAN_secondary_lang]['electronic_mail_address'] = single_value

            if len(primary_vals[CKAN_secondary_lang]) < 1:
                reportError(
                    HNAP_fileIdentifier,[
                        schema_ref["30"]['CKAN API property'],
                        'Value not found in '+schema_ref["30"]['Reference']
                    ])

            json_record[schema_ref["29"]['CKAN API property']] = json.dumps(primary_vals)

# CC::OpenMaps-31 Contact Email

            # Single report out, multiple records combined
            schema_ref["31"]['Occurrences'] = 'R'
            json_record[schema_ref["31"]['CKAN API property']] = {}

            # HACK - find out of there is a pointOfContact role provided
            ref = schema_ref["31"]["FGP XPATH"].split("gmd:CI_ResponsibleParty")[0] + "gmd:CI_ResponsibleParty[gmd:role/gmd:CI_RoleCode[@codeListValue='RI_414']]"
            tmp = fetchXMLValues(record, ref)
            xpath_sub = ""

            if len(tmp) > 0:
                xpath_sub = "gmd:CI_ResponsibleParty[gmd:role/gmd:CI_RoleCode[@codeListValue='RI_414']]"

            # value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["31"])
            value = fetch_FGP_value(record, HNAP_fileIdentifier, {"Requirement": schema_ref["31"]['Requirement'], "Occurrences": schema_ref["31"]['Occurrences'],"FGP XPATH": schema_ref["31"]["FGP XPATH"].replace("gmd:CI_ResponsibleParty", xpath_sub), "Value Type": schema_ref["31"]['Value Type'], "CKAN API property": schema_ref["31"]['CKAN API property']})

            # primary_data = []
            # if value:
            #     for single_value in value:
            #         primary_data.append(single_value)

            # if len(primary_data) > 0:
            #     json_record[schema_ref["31"]['CKAN API property']] = ','.join(value)

            # Check for valid email
            if value:
                isValidEmail = re.match(r'(^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$)', value[0])

                if not isValidEmail or isValidEmail == None:
                    reportError(
                        HNAP_fileIdentifier, [
                            schema_ref["31"]['CKAN API property'],
                            "Invalid Email",
                            value[0]
                        ])
                else:
                    json_record[schema_ref["31"]['CKAN API property']] = value[0]
            else:
                reportError(
                    HNAP_fileIdentifier, [
                        schema_ref["31"]['CKAN API property'],
                        "Invalid Email",
                        ''
                    ])


# CC::OpenMaps-32 Description (English)

            json_record[schema_ref["32"]['CKAN API property']] = {}
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["32"])
            if value:

                # format line breaks
                value = value.replace('\n', '  \n  \n  ')

                json_record[
                    schema_ref["32"]['CKAN API property']
                ][CKAN_primary_lang] = value

            # XXX Check that there are values

# CC::OpenMaps-33 Description (French)

            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["33"])
            if value:

                # format line breaks
                value = value.replace('\n', '  \n  \n  ')

                json_record[
                    schema_ref["32"]['CKAN API property']
                ][CKAN_secondary_lang] = value

            # XXX Check that there are values

# CC::OpenMaps-34 Keywords (English)

            primary_vals = []
            json_record[schema_ref["34"]['CKAN API property']] = {}
            json_record[schema_ref["34"]['CKAN API property']][CKAN_primary_lang] = []

            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["34"])
            if value:
                for single_value in value:
                    p = re.compile('^[A-Z][A-Z] [^>]+ > ')
                    single_value = p.sub('', single_value)
                    single_value = single_value.strip()
                    
# ADAPTATION #4
# 2016-05-27 - call
# Alexandre Bolieux asked I replace commas with something valid.  I'm replacing them with semi-colons
# which can act as a seperator character like the comma but get past that reserved character
                    single_value = single_value.replace(',', ';')
# END ADAPTATION
                    # remove multiple spaces
                    single_value = re.sub(r'\s+', ' ', single_value)
                    keyword_error = canada_tags(single_value).replace('"', '""')

# ADAPTATION #5
# 2016-05-27 - call
# Alexandre Bolieux asked if I could replace commas with something valid.  I'm
# replacing them with semi-colons which can act as a seperator character like
# the comma but get past that reserved character
                    if re.search('length is more than maximum 140', keyword_error, re.UNICODE):
                        pass
                    else:
# END ADAPTATION
                        if not keyword_error == '':
                        #if not re.search(schema_ref["34"]['RegEx Filter'], single_value,re.UNICODE):
                            reportError(
                                HNAP_fileIdentifier, [
                                    schema_ref["34"]['CKAN API property']+'-'+CKAN_primary_lang,
                                    "Invalid Keyword",
                                    keyword_error
                                    #"Must be alpha-numeric, space or '-_./>+& ["+single_value+']'
                                ])
                        else:
                            if single_value not in json_record[schema_ref["34"]['CKAN API property']][CKAN_primary_lang]:
                                json_record[schema_ref["34"]['CKAN API property']][CKAN_primary_lang].append(single_value)

#                        if not len(json_record[schema_ref["34"]['CKAN API property']][CKAN_primary_lang]):
#                            reportError(
#                                HNAP_fileIdentifier,[
#                                    schema_ref["34"]['CKAN API property']+'-'+CKAN_primary_lang,
#                                    "No keywords"
#                                ])

# CC::OpenMaps-35 Keywords (French)

            json_record[schema_ref["34"]['CKAN API property']][CKAN_secondary_lang] = []

            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["35"])
            if value:
                for single_value in value:
                    p = re.compile('^[A-Z][A-Z] [^>]+ > ')
                    single_value = p.sub('', single_value)
# ADAPTATION #4
# 2016-05-27 - call
# Alexandre Bolieux asked if I could replace commas with something valid.  I'm
# replacing them with semi-colons which can act as a seperator character like
# the comma but get past that reserved character
                    single_value = single_value.replace(',', ';')
# END ADAPTATION
                    single_value = re.sub(r'\s+', ' ', single_value)
                    keyword_error = canada_tags(single_value).replace('"', '""')

# ADAPTATION #5
# 2016-05-27 - call
# Alexandre Bolieux asked I drop keywords that exceed 140 characters
                    if re.search('length is more than maximum 140', keyword_error, re.UNICODE):
                        pass
                    else:
# END ADAPTATION
                        if not keyword_error == '':
                        #if not re.search(schema_ref["34"]['RegEx Filter'], single_value,re.UNICODE):
                            reportError(
                                HNAP_fileIdentifier, [
                                    schema_ref["34"]['CKAN API property']+'-'+CKAN_secondary_lang,
                                    "Invalid Keyword",
                                    keyword_error
                                    #'Must be alpha-numeric, space or -_./>+& ['+single_value+']'
                                ])
                        else:
                            if single_value not in json_record[schema_ref["34"]['CKAN API property']][CKAN_secondary_lang]:
                                json_record[schema_ref["34"]['CKAN API property']][CKAN_secondary_lang].append(single_value)

#                        if not len(json_record[schema_ref["34"]['CKAN API property']][CKAN_secondary_lang]):
#                            reportError(
#                                HNAP_fileIdentifier,[
#                                    schema_ref["34"]['CKAN API property']+'-'+CKAN_secondary_lang,
#                                    "No keywords"
#                                ])

# CC::OpenMaps-36 Subject

            subject_values = []
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["36"])
            if value:
                for subject in value:
                    termsValue = fetchCLValue(
                        subject.strip(), CL_Subjects)
                    if termsValue:
                        for single_item in termsValue[3].split(','):
                            subject_values.append(single_item.strip().lower())

                if len(subject_values) < 1:
                    reportError(
                        HNAP_fileIdentifier,[
                            schema_ref["36"]['CKAN API property'],
                            'Value not found in '+schema_ref["36"]['Reference']
                        ])
                else:
                    json_record[schema_ref["36"]['CKAN API property']] = list(set(subject_values))

# CC::OpenMaps-37 Topic Category

            topicCategory_values = []
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["37"])
            if value:
                for topicCategory in value:
                    termsValue = fetchCLValue(
                        topicCategory.strip(), napMD_KeywordTypeCode)
                    if termsValue:
                        topicCategory_values.append(termsValue[0])
                
                if len(topicCategory_values) < 1:
                    reportError(
                        HNAP_fileIdentifier,[
                            schema_ref["37"]['CKAN API property'],
                            'Value not found in '+schema_ref["37"]['Reference']
                        ])
                else:
                    json_record[schema_ref["37"]['CKAN API property']] = topicCategory_values

# CC::OpenMaps-38 Audience
# TBS 2016-04-13: Not in HNAP, we can skip

# CC::OpenMaps-39 Place of Publication (English)
# TBS 2016-04-13: Not in HNAP, we can skip

# CC::OpenMaps-40 Place of Publication  (French)
# TBS 2016-04-13: Not in HNAP, we can skip

# CC::OpenMaps-41 Spatial

            north = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["41n"])
            if north:
                south = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["41s"])
                if south:
                    east = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["41e"])
                    if east:
                        west = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["41w"])
                        if west:

                            # ensure we have proper numbers
                            north = [float(north[0]) if '.' in north[0] else int(north[0])]
                            east = [float(east[0]) if '.' in east[0] else int(east[0])]
                            south = [float(south[0]) if '.' in south[0] else int(south[0])]
                            west = [float(west[0]) if '.' in west[0] else int(west[0])]

                            GeoJSON = {}
                            GeoJSON['type'] = "Polygon"
                            GeoJSON['coordinates'] = [[
                                [west, south],
                                [east, south],
                                [east, north],
                                [west, north],
                                [west, south]
                            ]]

                            #json_record[schema_ref["41"]['CKAN API property']] = json.dumps(GeoJSON)
                            json_record[schema_ref["41"]['CKAN API property']] = '{"type": "Polygon","coordinates": [[[%s,%s],[%s,%s],[%s,%s],[%s,%s],[%s,%s]]]}' % (west[0],south[0],east[0],south[0],east[0],north[0],west[0],north[0],west[0],south[0])

# CC::OpenMaps-42 Geographic Region Name
# TBS 2016-04-13: Not in HNAP, we can skip (the only providing the bounding box, not the region name)

# CC::OpenMaps-43 Time Period Coverage Start Date
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["43"])
            if value:
                if sanityDate(
                    HNAP_fileIdentifier,[
                        schema_ref["43"]['CKAN API property']+'-start'
                    ],
                    maskDate(value)
                ):
                    json_record[schema_ref["43"]['CKAN API property']] = maskDate(value)

# CC::OpenMaps-44 Time Period Coverage End Date
#   ADAPTATION #2
#     CKAN (or Solr) requires an end date where one doesn't exist.  An open
#     record should run without an end date.  Since this is not the case a
#     '9999-99-99' is used in lieu.
#   ADAPTATION #3
#     Temporal elements are ISO 8601 date objects but this field may be
#     left blank (invalid).
#     The intent is to use a blank field as a maker for an "open" record
#     were omission of this field would be standard practice.  No
#     gml:endPosition = no end.
#     Since changing the source seems to be impossible we adapt by
#     replacing a blank entry with the equally ugly '9999-99-99' forced
#     end in CKAN.

            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["44"])
            if value:

                check_for_blank = value
                if check_for_blank == '':
                    check_for_blank = '9999-09-09'

                if sanityDate(
                    HNAP_fileIdentifier,[
                        schema_ref["44"]['CKAN API property']+'-end'
                    ],
                    maskDate(check_for_blank)
                ):
                    json_record[schema_ref["44"]['CKAN API property']] = maskDate(check_for_blank)

# CC::OpenMaps-45 Maintenance and Update Frequency

            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["45"])
            if value:
                # Can you find the CL entry?
                termsValue = fetchCLValue(value, napMD_MaintenanceFrequencyCode)
                if not termsValue:
                    reportError(
                        HNAP_fileIdentifier,[
                            schema_ref["45"]['CKAN API property'],
                            'Value not found in '+schema_ref["45"]['Reference']
                        ])
                else:
                    json_record[schema_ref["45"]['CKAN API property']] = termsValue[2]


# CC::OpenMaps-46 Date Published
# CC::OpenMaps-47 Date Modified

            ##################################################
            # These are a little different, we have to do these odd birds manually
            r = record.xpath(
                schema_ref["46"]["FGP XPATH"],
                namespaces={
                    'gmd': 'http://www.isotc211.org/2005/gmd',
                    'gco': 'http://www.isotc211.org/2005/gco'})      
                     
            if(len(r)):
                for cn in r:
                    input_types = {}
                    inKey = []
                    inVal = ''
                    # Decypher which side has the code and which has the data,
                    # yea... it changes -sigh-
                    # Keys will always use the ;
                    try:
                        if cn[0][0].text is not None and len(cn[0][0].text.split(';')) > 1:
                            inKey = cn[0][0].text.split(';')
                            inVal = cn[1][0].text.strip()
                        elif cn[1][0].text is not None:
                            inKey = cn[1][0].text.split(';')
                            inVal = cn[0][0].text.strip()
                    except:
                        pass

                    for input_type in inKey:
                        input_type = input_type.strip()
                        if input_type == u'publication':
                            if sanityDate(
                                    HNAP_fileIdentifier,[
                                        schema_ref["46"]['CKAN API property']
                                    ],
                                    maskDate(inVal)):
                                json_record[schema_ref["46"]['CKAN API property']] = maskDate(inVal)
                                break

                        if input_type == u'revision' or input_type == u'révision':
                            if sanityDate(
                                    HNAP_fileIdentifier,[
                                        schema_ref["47"]['CKAN API property']
                                    ],
                                    maskDate(inVal)):
                                json_record[schema_ref["47"]['CKAN API property']] = maskDate(inVal)
                                break

                # Check the field is populated if you have to
                if schema_ref["46"]['Requirement'] == 'M' and schema_ref["46"]['CKAN API property'] not in json_record:
                    reportError(
                        HNAP_fileIdentifier,[
                            schema_ref["46"]['CKAN API property'],
                            'Value not found in '+schema_ref["46"]['Reference']
                        ])

                # Check the field is populated if you have to
                if schema_ref["47"]['Requirement'] == 'M' and schema_ref["47"]['CKAN API property'] not in json_record:
                    reportError(
                        HNAP_fileIdentifier,[
                            schema_ref["47"]['CKAN API property'],
                            'Value not found in '+schema_ref["47"]['Reference']
                        ])


            if 'date_published' not in json_record:
                reportError(
                    HNAP_fileIdentifier,[
                        schema_ref["46"]['CKAN API property'],
                        'mandatory field missing'
                    ])

# CC::OpenMaps-48 Date Released
# SYSTEM GENERATED

# CC::OpenMaps-49 Homepage URL (English)
# TBS 2016-04-13: Not in HNAP, we can skip
# CC::OpenMaps-50 Homepage URL (French)
# TBS 2016-04-13: Not in HNAP, we can skip

# CC::OpenMaps-51 Series Name (English)
# TBS 2016-04-13: Not in HNAP, we can skip
# CC::OpenMaps-52 Series Name (French)
# TBS 2016-04-13: Not in HNAP, we can skip

# CC::OpenMaps-53 Series Issue Identification (English)
# TBS 2016-04-13: Not in HNAP, we can skip
# CC::OpenMaps-54 Series Issue Identification (French)
# TBS 2016-04-13: Not in HNAP, we can skip

# CC::OpenMaps-55 Digital Object Identifier
# TBS 2016-04-13: Not in HNAP, we can skip

# CC::OpenMaps-56 Reference System Information

            # Allow for multiple refrence definitions
            # Updated implementation mimics prior behaviour.
            possible_refrences = fetchXMLArray(
                record,
                schema_ref["56"]['FGP XPATH'])

            # print '--------------------------------------'
            # print possible_refrences
            # print '--------------------------------------'

            if len(possible_refrences) == 0:
                reportError(
                    HNAP_fileIdentifier,[
                        schema_ref["56"]['CKAN API property'],
                        'No projection information found'
                    ])
            else:
                first_full_triplet = ''
                for possible_refrence in possible_refrences:
                    vala = valb = valc = ''

                    # code
                    value = fetch_FGP_value(possible_refrence, HNAP_fileIdentifier, schema_ref["56a"])
                    if value:
                        vala = value
                    # codeSpace
                    value = fetch_FGP_value(possible_refrence, HNAP_fileIdentifier, schema_ref["56b"])
                    if value:
                        valb = value
                    # version
                    value = fetch_FGP_value(possible_refrence, HNAP_fileIdentifier, schema_ref["56c"])
                    if value:
                        valc = value

                    # Apply your business logic, this is the same logic as before assuming a single projection
                    # If this is to become multiple projections the property needs to be changed into an array
                    # in the schema and _then_ in CKAN.
                    if vala != '' and valb != '' and valc != '':
                        first_full_triplet = vala+','+valb+','+valc
                        json_record[schema_ref["56"]['CKAN API property']] = first_full_triplet
                        break
                
                # if the triplet is not complete then fail over to just the mandatory HNAP requirement
                if first_full_triplet == '':

                    rs_identifier = fetch_FGP_value(possible_refrences[0], HNAP_fileIdentifier, schema_ref["56a"])

                    if len(rs_identifier) > 0:

                        first_full_triplet = rs_identifier+','+fetch_FGP_value(possible_refrences[0], HNAP_fileIdentifier, schema_ref["56b"])+','+fetch_FGP_value(possible_refrences[0], HNAP_fileIdentifier, schema_ref["56c"])
                    
                    if first_full_triplet == '':
                        reportError(
                            HNAP_fileIdentifier,[
                                schema_ref["56"]['CKAN API property'],
                                'Complete triplet not found'
                            ])

# CC::OpenMaps-57 Distributor (English)

            primary_vals = {}
            primary_vals[CKAN_primary_lang] = {}
            primary_vals[CKAN_secondary_lang] = {}

            # organizationName
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["57a"])
            if value:
                for single_value in value:
                    primary_vals[CKAN_primary_lang]['organization_name'] = single_value
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["58a"])
            if value:
                for single_value in value:
                    primary_vals[CKAN_secondary_lang]['organization_name'] = single_value

            # phone
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["57b"])
            if value:
                for single_value in value:
                    primary_vals[CKAN_primary_lang]['phone'] = single_value
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["58b"])
            if value:
                for single_value in value:
                    primary_vals[CKAN_secondary_lang]['phone'] = single_value

            # address
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["57c"])
            if value:
                for single_value in value:
                    primary_vals[CKAN_primary_lang]['address'] = single_value
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["58c"])
            if value:
                for single_value in value:
                    primary_vals[CKAN_secondary_lang]['address'] = single_value

            # city
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["57d"])
            if value:
                for single_value in value:
                    primary_vals[CKAN_primary_lang]['city'] = single_value
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["58d"])
            if value:
                for single_value in value:
                    primary_vals[CKAN_secondary_lang]['city'] = single_value

            # administrativeArea
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["57e"])
            if value:
                for single_value in value:
                    primary_vals[CKAN_primary_lang]['administrative_area'] = single_value
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["58e"])
            if value:
                for single_value in value:
                    primary_vals[CKAN_secondary_lang]['administrative_area'] = single_value

            # postalCode
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["57f"])
            if value:
                for single_value in value:
                    primary_vals[CKAN_primary_lang]['postal_code'] = single_value
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["58f"])
            if value:
                for single_value in value:
                    primary_vals[CKAN_secondary_lang]['postal_code'] = single_value

            # country
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["57g"])
            if value:
                for single_value in value:
                    primary_vals[CKAN_primary_lang]['country'] = single_value
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["58g"])
            if value:
                for single_value in value:
                    primary_vals[CKAN_secondary_lang]['country'] = single_value

            # electronicMailAddress  mandatory
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["57h"])
            if value:
                for single_value in value:
                    primary_vals[CKAN_primary_lang]['electronic_mail_address'] = single_value
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["58h"])
            if value:
                for single_value in value:
                    primary_vals[CKAN_secondary_lang]['electronic_mail_address'] = single_value

            # role mandatory
            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["57i"])
            if value:
                for single_value in value:
                    # Can you find the CL entry?
                    termsValue = fetchCLValue(single_value, napCI_RoleCode)
                    if not termsValue:
                        reportError(
                            HNAP_fileIdentifier,[
                                schema_ref["57"]['CKAN API property'],
                                'Value not found in '+schema_ref["57"]['Reference']
                            ])
                    else:
                        primary_vals[CKAN_primary_lang]['role'] = termsValue[0]
                        primary_vals[CKAN_secondary_lang]['role'] = termsValue[1]

            json_record[schema_ref["57"]['CKAN API property']] = json.dumps(primary_vals)

            #json_record[schema_ref["57"]['CKAN API property']] = {}
            #json_record[schema_ref["57"]['CKAN API property']][CKAN_primary_lang] = ','.join(primary_vals)
            #json_record[schema_ref["57"]['CKAN API property']][CKAN_secondary_lang] = ','.join(second_vals)

# CC::OpenMaps-59 Status

            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["59"])
            if value:
                # Can you find the CL entry?
                termsValue = fetchCLValue(value, napMD_ProgressCode)
                if not termsValue:
                    reportError(
                        HNAP_fileIdentifier,[
                            schema_ref["59"]['CKAN API property'],
                            'Value not found in '+schema_ref["59"]['Reference']
                        ])
                else:
                    json_record[schema_ref["59"]['CKAN API property']] = termsValue[0]

# CC::OpenMaps-60 Association Type

            associationTypes_array = []

            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["60"])
            # Not mandatory, process if you have it
            if value and len(value) > 0:
                # You have to itterate to find a valid one, not neccesaraly the
                for associationType in value:
                    # Can you find the CL entry?
                    termsValue = fetchCLValue(
                        associationType, napDS_AssociationTypeCode)
                    if not termsValue:
                        termsValue = []
                    else:
                        associationTypes_array.append(termsValue[2])

            if len(associationTypes_array):
                json_record[schema_ref["60"]['CKAN API property']] = ','.join(associationTypes_array)

# CC::OpenMaps-61 Aggregate Dataset Identifier

            aggregateDataSetIdentifier_array = []

            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["61"])
            # Not mandatory, process if you have it
            if value and len(value) > 0:

                try:
                    for aggregateDataSetIdentifier in value:
                        (primary, secondary) =\
                            aggregateDataSetIdentifier.strip().split(';')
                        aggregateDataSetIdentifier_array.append(primary.strip())
                        aggregateDataSetIdentifier_array.append(secondary.strip())
                except ValueError:
                    errorInfo = [schema_ref["61"]['CKAN API property']]
                    errorInfo.append('primary/secondary identifiers not provided/valid')
                    errorInfo.append(aggregateDataSetIdentifier.strip())
                    reportError(HNAP_fileIdentifier, errorInfo)
                    pass

            json_record[schema_ref["61"]['CKAN API property']] = ','.join(
                aggregateDataSetIdentifier_array)

# CC::OpenMaps-62 Spatial Representation Type

            value = fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref["62"])

            json_record[schema_ref["62"]['CKAN API property']] = {}
            spatialRepresentationType_array = []

            if value:
                # You have to itterate to find a valid one,
                # not neccesaraly the first
                for spatialRepresentationType in value:
                    # Can you find the CL entry?
                    termsValue = fetchCLValue(
                        spatialRepresentationType,
                        napMD_SpatialRepresentationTypeCode)
                    if not termsValue:
                        termsValue = []
                    else:
                        spatialRepresentationType_array.append(termsValue[0])
            
            # json_record[schema_ref["62"]['CKAN API property']] = ','.join(
            # spatialRepresentationType_array)

            json_record[schema_ref["62"]['CKAN API property']] = spatialRepresentationType_array

# CC::OpenMaps-63 Jurisdiction
# TBS 2016-04-13: Not in HNAP, but can we default text to ‘Federal’ / ‘Fédéral

            json_record[schema_ref["63"]['CKAN API property']] = schema_ref["63"]['FGP XPATH']

# CC::OpenMaps-64 Licence
# TBS (call): use ca-ogl-lgo

            json_record[schema_ref["64"]['CKAN API property']] = schema_ref["64"]['FGP XPATH']

# Ignored code from previous harvestor that would trigger an error on
# invalid supplied licences.  We now assume the OGL is understood as
# part of the participation.
# 
#        # OGDMES-35 licence_id
#        ##################################################
#        OGDMES_property = 'licence_id'
#        json_record['license_id'] = 'ca-ogl-lgo'
#        debug_output[
#            '35-OGDMES Licence'] = (
#            "Open Government Licence – Canada "
#            "<linkto: http://open.canada.ca/en/open-government-licence-canada>"
#            )
#
#        data_constraints = fetchXMLArray(
#            record,
#            "gmd:identificationInfo/" +
#            "gmd:MD_DataIdentification/" +
#            "gmd:resourceConstraints")
#        licence_count = 0
#        for data_constraint in data_constraints:
#            accessConstraint = False
#            useConstraint = False
#            tmp = fetchXMLAttribute(
#                data_constraint,
#                "gmd:MD_LegalConstraints/" +
#                "gmd:accessConstraints/" +
#                "gmd:MD_RestrictionCode",
#                "codeListValue")
#            if len(tmp) and tmp[0] == 'RI_606':  # RI_606 is a licence
#                accessConstraint = True
#            tmp = fetchXMLAttribute(
#                data_constraint,
#                "gmd:MD_LegalConstraints/" +
#                "gmd:useConstraints/" +
#                "gmd:MD_RestrictionCode",
#                "codeListValue")
#            if len(tmp) and tmp[0] == 'RI_606':  # RI_606 is a licence
#                useConstraint = True
#
#            if accessConstraint or useConstraint:
#                licence_count += 1
#
#                tmp = fetchXMLValues(
#                    data_constraint,
#                    "gmd:MD_LegalConstraints/" +
#                    "gmd:useLimitation/" +
#                    "gco:CharacterString")
#                if sanityMandatory(
#                        OGDMES_property +
#                        ',' +
#                        OGDMES_property,
#                        tmp):
#                    if sanityFirst(tmp).strip(
#                    ) != (
#                            'Open Government Licence - Canada '
#                            '(http://open.canada.ca/en/'
#                            'open-government-licence-canada)'
#                    ):
#                        reportError(
#                            OGDMES_fileIdentifier +
#                            ',' +
#                            'license,Invalid License,"' +
#                            str(tmp) +
#                            '"')
#
#                tmp = fetchXMLValues(
#                    data_constraint,
#                    "gmd:MD_LegalConstraints/" +
#                    "gmd:useLimitation/" +
#                    "gmd:PT_FreeText/" +
#                    "gmd:textGroup/gmd:LocalisedCharacterString")
#                if sanityMandatory(
#                        OGDMES_property +
#                        ',' +
#                        OGDMES_property,
#                        tmp):
#                    if sanityFirst(tmp).strip(
#                    ) != (
#                        'Licence du gouvernement ouvert - Canada '
#                        '(http://ouvert.canada.ca/fr/'
#                        'licence-du-gouvernement-ouvert-canada)'
#                    ):
#                        reportError(
#                            OGDMES_fileIdentifier +
#                            ',' +
#                            'license,Invalid License,"' +
#                            str(tmp) +
#                            '"')
#        if licence_count > 1:
#            reportError(
#                OGDMES_fileIdentifier +
#                ',' +
#                'license,More than one licence,""')

# CC::OpenMaps-65 Unique Identifier
# System generated

#### Resources

# CC::OpenMaps-68 Date Published
# TBS 2016-04-13: Not in HNAP, we can skip

# ADAPTATION #1
# The source METADATA (HNAP) does not seem to have the metadata
# required to describe the resouces for the client side.  It
# does not track resources content type, format or language.
# Without these it's impossible to create a proper download
# interface.
#
# This is to be corrected in HNAP by Sept. 1st 2015, more
# likely we review it then.
#
# From: Mitchell, Cindy [Cindy.Mitchell@NRCan-RNCan.gc.ca]
# Sent: February-27-15 10:39 AM
# To: Majewski, Chris; Hilt, Alannah; Martin,
# Marie-Eve: NRCAN.RNCAN; Matson, Arthur: NRCAN.RNCAN;
# Rupert, James: NRCAN.RNCAN; Rushforth, Peter: NRCAN.RNCAN;
# Weech, Mike: EC.EC; Shaw, Shaw: EC.EC; Bourgon,
# Jean-Francois: NRCAN.RNCAN; Thompson, Ross: SC.SC;
# Casovan, Ashley; Roussel, Pascale: NRCAN.RNCAN
# Cc: Shaw, Shaw: EC.EC
# Subject: RE: GUIDANCE FOR 5.20.5 DESCRIPTION :
#          OGDMES vs HNAP Mapping Part 2
#
# Oh have mercy my friend J.
#
# How about September 1?

            json_record['resources'] = []
            record_resources = fetchXMLArray(
                record,
                "gmd:distributionInfo/" +
                "gmd:MD_Distribution/" +
                "gmd:transferOptions/" +
                "gmd:MD_DigitalTransferOptions/" +
                "gmd:onLine/" +
                "gmd:CI_OnlineResource")

            resource_no = 0
            for resource in record_resources:

                resource_no += 1

                json_record_resource = {}
                json_record_resource[schema_ref["66"]['CKAN API property']] = {}

# CC::OpenMaps-66 Title (English)

                value = fetch_FGP_value(resource, HNAP_fileIdentifier, schema_ref["66"])
                if value:
                    json_record_resource[schema_ref["66"]['CKAN API property']][CKAN_primary_lang] = value

# CC::OpenMaps-67 Title (English)

                value = fetch_FGP_value(resource, HNAP_fileIdentifier, schema_ref["67"])
                if value:
                    json_record_resource[schema_ref["66"]['CKAN API property']][CKAN_secondary_lang] = value

# CC::OpenMaps-69 Resource Type
# CC::OpenMaps-70 Format
# CC::OpenMaps-73 Language

                value = fetch_FGP_value(resource, HNAP_fileIdentifier, schema_ref["69-70-73"])
                if value:
                    description_text = value.strip()

                    if description_text.count(';') != 2:
                        reportError(
                            HNAP_fileIdentifier,[
                                schema_ref["69-70-73"]['CKAN API property'],
                                'Content, Format or Language missing, must be: contentType;format;lang,lang',
                                description_text
                            ])
                    else:
                        (res_contentType, res_format,
                         res_language) = description_text.split(';')

                        languages_in = res_language.strip().split(',')
                        languages_out = []
                        for language in languages_in:
                            if language.strip() == 'eng':
                                languages_out.append('en')
                            if language.strip() == 'fra':
                                languages_out.append('fr')
                            if language.strip() == 'zxx': # Non linguistic
                                languages_out.append('zxx')
                        # language_str = ','.join(languages_out)
                        language_str = []
                        for langStr in languages_out:
                            language_str.append(langStr)

                        json_record_resource[schema_ref["69"]['CKAN API property']] = res_contentType.strip().lower()
                        json_record_resource[schema_ref["70"]['CKAN API property']] = res_format.strip()
                        json_record_resource[schema_ref["73"]['CKAN API property']] = language_str

                        #XXX Super duper hack
                        if json_record_resource[schema_ref["69"]['CKAN API property']] == 'document de soutien':
                            json_record_resource[schema_ref["69"]['CKAN API property']] = 'guide'
                        if json_record_resource[schema_ref["69"]['CKAN API property']] == 'supporting document':
                            json_record_resource[schema_ref["69"]['CKAN API property']] = 'guide'
                        if json_record_resource[schema_ref["69"]['CKAN API property']] == 'Supporting Documents':
                            json_record_resource[schema_ref["69"]['CKAN API property']] = 'guide'
                        if json_record_resource[schema_ref["69"]['CKAN API property']] == 'Supporting Document':
                            json_record_resource[schema_ref["69"]['CKAN API property']] = 'guide'
                        if json_record_resource[schema_ref["69"]['CKAN API property']] == 'web service':
                            json_record_resource[schema_ref["69"]['CKAN API property']] = 'web_service'
                        if json_record_resource[schema_ref["69"]['CKAN API property']] == u'données':
                            json_record_resource[schema_ref["69"]['CKAN API property']] = 'dataset'

                        if json_record_resource[schema_ref["70"]['CKAN API property']] == 'Web App':
                            json_record_resource[schema_ref["70"]['CKAN API property']] = 'HTML'
                        if json_record_resource[schema_ref["70"]['CKAN API property']] == 'IOS Application':
                            json_record_resource[schema_ref["70"]['CKAN API property']] = 'IPA'
                        if json_record_resource[schema_ref["70"]['CKAN API property']] == 'Blackberry Application':
                            json_record_resource[schema_ref["70"]['CKAN API property']] = 'COD'
                        if json_record_resource[schema_ref["70"]['CKAN API property']] == 'Windows Mobile':
                            json_record_resource[schema_ref["70"]['CKAN API property']] = 'EXE'
                        if json_record_resource[schema_ref["70"]['CKAN API property']] == 'Android Application':
                            json_record_resource[schema_ref["70"]['CKAN API property']] = 'APK'
                        if json_record_resource[schema_ref["70"]['CKAN API property']] == 'GeoJSON':
                            json_record_resource[schema_ref["70"]['CKAN API property']] = 'GEOJSON'
                        if json_record_resource[schema_ref["70"]['CKAN API property']] == 'dxf':
                            json_record_resource[schema_ref["70"]['CKAN API property']] = 'DXF'

                else:
                    reportError(
                        HNAP_fileIdentifier,[
                            schema_ref["69-70-73"]['CKAN API property'],
                            'format,mandatory field missing'
                        ])
                    reportError(
                        HNAP_fileIdentifier,[
                            schema_ref["69-70-73"]['CKAN API property'],
                            'language,mandatory field missing'
                        ])
                    reportError(
                        HNAP_fileIdentifier,[
                            schema_ref["69-70-73"]['CKAN API property'],
                            'contentType,mandatory field missing'
                        ])

                if json_record_resource[schema_ref["69"]['CKAN API property']].lower() not in ResourceType:
                    reportError(
                        HNAP_fileIdentifier,[
                            schema_ref["69-70-73"]['CKAN API property'],
                            'invalid resource type',
                            json_record_resource[schema_ref["69"]['CKAN API property']]
                        ])
                else:
                    json_record_resource[schema_ref["69"]['CKAN API property']] = ResourceType[json_record_resource[schema_ref["69"]['CKAN API property']].lower()][0]

                if json_record_resource[schema_ref["70"]['CKAN API property']] not in CL_Formats:
                    reportError(
                        HNAP_fileIdentifier,[
                            schema_ref["69-70-73"]['CKAN API property'],
                            'invalid resource format',
                            json_record_resource[schema_ref["70"]['CKAN API property']]
                        ])

# CC::OpenMaps-71 Character Set
# TBS 2016-04-13: Not in HNAP, we can skip
# CC::OpenMaps-74 Size
# TBS 2016-04-13: Not in HNAP, we can skip

# CC::OpenMaps-74 Download URL

                value = fetch_FGP_value(resource, HNAP_fileIdentifier, schema_ref["74"])
                if value:
                    json_record_resource[schema_ref["74"]['CKAN API property']] = value
                else:
                    reportError(
                        HNAP_fileIdentifier,[
                            schema_ref["74"]['CKAN API property'],
                            'URL, mandatory field missing'
                        ])


# CC::OpenMaps-75 Title (English)
# XXX Need to confirm why this is not included
#            json_record[schema_ref["75"]['CKAN API property']] = {}
#
#            value = fetch_FGP_value(resource, HNAP_fileIdentifier, schema_ref["75"])
#            if value:
#                json_record[schema_ref["75"]['CKAN API property']][CKAN_primary_lang] = value

# CC::OpenMaps-76 Title (French)
# XXX Need to confirm why this is not included
#            value = fetch_FGP_value(resource, HNAP_fileIdentifier, schema_ref["76"])
#            if value:
#                json_record[schema_ref["75"]['CKAN API property']][CKAN_secondary_lang] = value

# CC::OpenMaps-76 Record Type
# TBS 2016-04-13: Not in HNAP, we can skip
# CC::OpenMaps-78 Relationship Type
# TBS 2016-04-13: Not in HNAP, we can skip
# CC::OpenMaps-79 Language
# TBS 2016-04-13: Not in HNAP, we can skip
# CC::OpenMaps-80 Record URL
# TBS 2016-04-13: Not in HNAP, we can skip

# CC::OpenMaps-81 Mappable
# Stored as a generic Display Flag in preperation for other forms of visualizations

                #if schema_ref["81"]['CKAN API property'] not in json_record:
                #    can_be_used_in_RAMP = False
                #    json_record[schema_ref["81"]['CKAN API property']] = can_be_used_in_RAMP

                # If false check if true now
                if not can_be_used_in_RAMP:
                    value = fetch_FGP_value(resource, HNAP_fileIdentifier, schema_ref["81"])
                    if value:
                        protocol_desc = value.strip()
                        if protocol_desc in mappable_protocols:
                            can_be_used_in_RAMP = True
                            
                            # check to see if the URL is HTTPS
                            value = fetch_FGP_value(resource, HNAP_fileIdentifier, schema_ref["74"])
                            # if value[:value.find(":")] == 'http':
                                # print "No HTTPS: " + HNAP_fileIdentifier
                            if value:
                                can_be_used_in_RAMP = value[:value.find(":")] == 'https'

                # Append the resource to the Open Maps record
                json_record['resources'].append(json_record_resource)
            
            # TODO Add parent relation if exists
            # json_record['resources'].append( { "relation_type" : "info" } )

            #json_record[schema_ref["81"]['CKAN API property']] = can_be_used_in_RAMP
            view_on_map = ""
            if can_be_used_in_RAMP:
                json_record['display_flags'].append('fgp_viewer')
                view_on_map = " [ View on Map ]"
                num_view_on_map += 1


            ##################################################
            #                                                #
            # Accept or Reject                               #
            # Assume IMSO approval                           #
            # Assume publish status                          #
            # Assume active status                           #
            # Append to list of Datasets                     #
            #                                                #
            ##################################################

            if HNAP_fileIdentifier in error_records:
                print "\x1b[0;37;41m Reject: \x1b[0m "+str(HNAP_fileIdentifier) + view_on_map
                num_rejects += 1
            else:
                print "\x1b[0;37;42m Accept: \x1b[0m "+str(HNAP_fileIdentifier) + view_on_map
                json_record['imso_approval'] = 'true'
                json_record['ready_to_publish'] = 'true'
                json_record['state'] = 'active'
                json_record['restrictions'] = 'unrestricted'
                # if error don't do this
                json_records.append(json_record)

            ##################################################
            #                                                #
            # Move onto the next record                      #
            #                                                #
            ##################################################

    if len(json_records) > 0:
        print ""
        print "Generating Common Core JSON file for import to CKAN...",

    # Write JSON Lines to files
    output = codecs.open(output_jl, 'w', 'utf-8')
    for json_record in json_records:
        utf_8_output =\
        json.dumps(
            json_record,
            #sort_keys=True,
            #indent=4,
            ensure_ascii=False,
            encoding='utf8')
        #print utf_8_output
        output.write(utf_8_output+"\n")
    output.close()

    if len(json_records) > 0:
        print "Done!"
        print ""
        print "* Number of records accepted: "+str(len(json_records))
        print ""
        print "* Number of records rejected: "+str(num_rejects)
        print ""
        print "* Number with view on map:    "+str(num_view_on_map)
        print ""
        print "* Number of errors logged:    "+str(len(error_output)) + " [ harvested_record_errors.csv | harvested_record_errors.html ]"
        print ""
 
    output = codecs.open(output_err, 'w', 'utf-8')
    if len(error_output) > 0:
        output.write('"id","field","description","value"'+u"\n")
    for error in error_output:
        #output.write(unicode(error+"\n", 'utf-8'))
        output.write(error+u"\n")
    output.close()

##################################################
# Reporting, Sanity and Access functions
# reportError(HNAP_fileIdentifier, errorInfo)
# sanityMandatory(pre, values)
# sanitySingle(pre, values)
# sanityDate(pre, date_text)
# sanityFirst(values)

# Fire off an error to cmd line
def reportError(HNAP_fileIdentifier,errorInfo):
    errorText = '"'+HNAP_fileIdentifier+'","'+'","'.join(errorInfo)+'"'
    global error_output
    global error_records
    #global OGDMES2ID
    #print len(error_output)
    if not isinstance(errorText, unicode):
        errorText = unicode(errorText, 'utf-8')
    error_output.append(errorText)
    if HNAP_fileIdentifier not in error_records:
        error_records[HNAP_fileIdentifier] = []
    error_records[HNAP_fileIdentifier].append(errorText)
    #print len(error_output)
# Sanity check: make sure the value exists
def sanityMandatory(HNAP_fileIdentifier,errorInfo, values):
    values = list(set(values))
    if values is None or len(values) < 1:
        errorInfo.append('mandatory field missing or not found in controlled list')
        reportError(HNAP_fileIdentifier,errorInfo)
        return False
    return True
# Sanity check: make sure there is only one value
def sanitySingle(HNAP_fileIdentifier,errorInfo, values):
    values = list(set(values))
    if len(values) > 1:
        errorInfo.append('multiple of a single value')
        errorInfo.append(','.join(values))
        reportError(HNAP_fileIdentifier,errorInfo)
        return False
    return True
# Sanity check: validate the date
def sanityDate(HNAP_fileIdentifier,errorInfo, date_text):
    value = ''
    try:
        value = datetime.datetime.strptime(
            date_text,
            '%Y-%m-%d').isoformat().split('T')[0]
    except ValueError:
        errorInfo.append('date is not valid')
        errorInfo.append(date_text)
        reportError(HNAP_fileIdentifier, errorInfo)
        return False
    if value != date_text:
        errorInfo.append('date is not valid')
        errorInfo.append(date_text)
        reportError(HNAP_fileIdentifier, errorInfo)
        return False
    return True
# Sanity value: extract the first value or blank string
def sanityFirst(values):
    if len(values) < 1:
        return ''
    else:
        return values[0]

##################################################
# Project specific data manipulation
# maskDate(date)


def maskDate(date):
    # default_date =\
    if len(date) >= 10:
        return date
    return date + ('xxxx-01-01'[-10 + len(date):])

##################################################
# XML Extract functions
# fetchXMLArray(objectToXpath, xpath)
# fetchXMLValues(objectToXpath, xpath)
# fetchXMLAttribute(objectToXpath, xpath, attribute)
# fetchCLValue(SRCH_key, CL_array)


# Fetch an array which may be subsections
def fetchXMLArray(objectToXpath, xpath):
    return objectToXpath.xpath(xpath, namespaces={
        'gmd': 'http://www.isotc211.org/2005/gmd',
        'gco': 'http://www.isotc211.org/2005/gco',
        'gml': 'http://www.opengis.net/gml/3.2',
        'csw': 'http://www.opengis.net/cat/csw/2.0.2'})


# Extract values from your current position
def fetchXMLValues(objectToXpath, xpath):
    values = []
    r = fetchXMLArray(objectToXpath, xpath)
    if(len(r)):
        for namePart in r:
            if namePart.text is None:
                values.append('')
            else:
                values.append(namePart.text.strip())
    return values


# Fetch an attribute instead of a an element
def fetchXMLAttribute(objectToXpath, xpath, attribute):
    # Easy to miss this, clean and combine
    clean_xpath = xpath.rstrip('/')
    clean_attribute = xpath.lstrip('@')
    # Access to an attribute through lxml is
    # xpath/to/key/@key_attribute
    # e.g.:
    # html/body/@background-color
    return objectToXpath.xpath(xpath + '/@' + attribute, namespaces={
        'gmd': 'http://www.isotc211.org/2005/gmd',
        'gco': 'http://www.isotc211.org/2005/gco',
        'gml': 'http://www.opengis.net/gml/3.2',
        'csw': 'http://www.opengis.net/cat/csw/2.0.2'})


# Fetch the value of a controled list ( at the bottom )
def fetchCLValue(SRCH_key, CL_array):
    p = re.compile(' ')
    SRCH_key = SRCH_key.lower()
    SRCH_key = p.sub('', SRCH_key)
    for CL_key, value in CL_array.items():
        CL_key = CL_key.lower()
        CL_key = p.sub('', CL_key)
        CL_key = unicode(CL_key, errors='ignore')
        if SRCH_key == CL_key:
            return value
    return None


# Schema aware fetch for generic items
def fetch_FGP_value(record, HNAP_fileIdentifier, schema_ref):
    if schema_ref['Value Type'] == 'value':
        tmp = fetchXMLValues(
            record,
            schema_ref["FGP XPATH"])
    elif schema_ref['Value Type'] == 'attribute':
        tmp = fetchXMLAttribute(
            record,
            schema_ref["FGP XPATH"],
            "codeListValue")
    else:
        reportError(
            HNAP_fileIdentifier, [
                schema_ref['CKAN API property'],
                'FETCH on undefined Value Type',
                schema_ref['CKAN API property']+':'+schema_ref['Value Type']
            ])
        return False

    if schema_ref['Requirement'] == 'M':
        if not sanityMandatory(
            HNAP_fileIdentifier, [
                schema_ref['CKAN API property']
            ],
            tmp
        ):
            return False
    if schema_ref['Occurrences'] == 'S':
        if not sanitySingle(
            HNAP_fileIdentifier, [
                schema_ref['CKAN API property']
            ],
            tmp
        ):
            return False
        else:
            return sanityFirst(tmp)

    return tmp

##################################################
# External validators
# canada_tags(value)

# Unceremoniously appropriated/repurposed from Ian Ward's change to CKAN and
# clubbed into a shape I can use here.
# https://github.com/open-data/ckanext-canada/commit/711236e39922d167991dc56a06e53f8328b11c4c
# I should pull these tests in from CKAN but we don't have time to do the smart
# thing quite yet.  Eventually I'll collect these errors from my attempt to
# upload them to CKAN to keep up to date.  This happens when we generate system
# level documentation to match.
def canada_tags(value):
    """
    Accept
    - unicode graphical (printable) characters
    - single internal spaces (no double-spaces)

    Reject
    - commas
    - tags that are too short or too long

    Strip
    - spaces at beginning and end
    """
    value = value.strip()

    if len(value) < MIN_TAG_LENGTH:
        return  u'Tag "%s" length is less than minimum %s' % (value, MIN_TAG_LENGTH)
    if len(value) > MAX_TAG_LENGTH:
        return u'Tag "%s" length is more than maximum %i'  % (value, MAX_TAG_LENGTH)
    if u',' in value:
        return u'Tag "%s" may not contain commas' % (value)
    if u'  ' in value:
        return u'Tag "%s" may not contain consecutive spaces' % (value)

    caution = re.sub(ur'[\w ]*', u'', value)
    for ch in caution:
        category = unicodedata.category(ch)
        if category.startswith('C'):
            return u'Tag "%s" may not contain unprintable character U+%04x' % (value, ord(ch))
        if category.startswith('Z'):
            return u'Tag "%s" may not contain separator charater U+%04x' % (value, ord(ch))

    return ''

##################################################
# FGP specific Controled lists
#
# Citation-Role
# IC_90
# http://nap.geogratis.gc.ca/metadata/register/registerItemClasses-eng.html#IC_90
# napCI_RoleCode {}
#
# Status
# IC_106
# http://nap.geogratis.gc.ca/metadata/register/registerItemClasses-eng.html#IC_106
# napMD_ProgressCode
#
# Association Type
# IC_92
# http://nap.geogratis.gc.ca/metadata/register/registerItemClasses-eng.html#IC_92
# napDS_AssociationTypeCode
#
# spatialRespresentionType
# IC_109
# http://nap.geogratis.gc.ca/metadata/register/registerItemClasses-eng.html#IC_109
# napMD_SpatialRepresentationTypeCode
#
# maintenanceAndUpdateFrequency
# IC_102
# http://nap.geogratis.gc.ca/metadata/register/registerItemClasses-eng.html#IC_102
# napMD_MaintenanceFrequencyCode
#
# presentationForm
# IC_89
# http://nap.geogratis.gc.ca/metadata/register/registerItemClasses-eng.html#IC_89
# presentationForm
#
# Mapping to CKAN required values
# napMD_MaintenanceFrequencyCode
# napMD_KeywordTypeCode
#
# GC_Registry_of_Applied_Terms {}
# OGP_catalogueType


#Citation-Role
#IC_90    http://nap.geogratis.gc.ca/metadata/register/registerItemClasses-eng.html#IC_90
napCI_RoleCode = {
    'RI_408'    : [u'resource_provider',        u'resourceProvider',         u'fournisseurRessource'],
    'RI_409'    : [u'custodian',                u'custodian',                u'conservateur'],
    'RI_410'    : [u'owner',                    u'owner',                    u'propriétaire'],
    'RI_411'    : [u'user',                     u'user',                     u'utilisateur'],
    'RI_412'    : [u'distributor',              u'distributor',              u'distributeur'],
    'RI_413'    : [u'originator',               u'originator',                u'créateur'],
    'RI_414'    : [u'point_of_contact',         u'pointOfContact',           u'contact'],
    'RI_415'    : [u'principal_investigator',   u'principalInvestigator',    u'chercheurPrincipal'],
    'RI_416'    : [u'processor',                u'processor',                u'traiteur'],
    'RI_417'    : [u'publisher',                u'publisher',                u'éditeur'],
    'RI_418'    : [u'author',                   u'author',                   u'auteur'],
    'RI_419'    : [u'collaborator',             u'collaborator',             u'collaborateur'],
    'RI_420'    : [u'editor',                   u'editor',                   u'réviseur'],
    'RI_421'    : [u'mediator',                 u'mediator',                 u'médiateur'],
    'RI_422'    : [u'rights_holder',            u'rightsHolder',             u'détenteurDroits']
}

#Status
#IC_106    http://nap.geogratis.gc.ca/metadata/register/registerItemClasses-eng.html#IC_106
napMD_ProgressCode = {
    'RI_593'    : [u'completed',                u'completed',                u'complété'],
    'RI_594'    : [u'historical_archive',       u'historicalArchive',        u'archiveHistorique'],
    'RI_595'    : [u'obsolete',                 u'obsolete',                 u'périmé'],
    'RI_596'    : [u'ongoing',                  u'onGoing',                  u'enContinue'],
    'RI_597'    : [u'planned',                  u'planned',                  u'planifié'],
    'RI_598'    : [u'required',                 u'required',                 u'requis'],
    'RI_599'    : [u'under_development',        u'underDevelopment',         u'enProduction'],
    'RI_600'    : [u'proposed',                 u'proposed',                 u'proposé']
}

#Association Type
#IC_92    http://nap.geogratis.gc.ca/metadata/register/registerItemClasses-eng.html#IC_92
napDS_AssociationTypeCode = {
    'RI_428'    : [u'crossReference',           u'référenceCroisée',                u'cross_reference'],
    'RI_429'    : [u'largerWorkCitation',       u'référenceGénérique',              u'larger_work_citation'],
    'RI_430'    : [u'partOfSeamlessDatabase',   u'partieDeBaseDeDonnéesContinue',   u'part_of_seamless_database'],
    'RI_431'    : [u'source',                   u'source',                          u'source'],
    'RI_432'    : [u'stereoMate',               u'stéréoAssociée',                  u'stereo_mate'],
    'RI_433'    : [u'isComposedOf',             u'estComposéDe',                    u'is_composed_of']
}

#spatialRespresentionType
#IC_109    http://nap.geogratis.gc.ca/metadata/register/registerItemClasses-eng.html#IC_109
napMD_SpatialRepresentationTypeCode = {
    'RI_635'    : [u'vector',                   u'vector',                   u'vecteur'],
    'RI_636'    : [u'grid',                     u'grid',                     u'grille'],
    'RI_637'    : [u'text_table',               u'textTable',                u'texteTable'],
    'RI_638'    : [u'tin',                      u'tin',                      u'tin'],
    'RI_639'    : [u'stereo_model',             u'stereoModel',              u'stéréomodèle'],
    'RI_640'    : [u'video',                    u'vidéo']
}

#maintenanceAndUpdateFrequency
#IC_102    http://nap.geogratis.gc.ca/metadata/register/registerItemClasses-eng.html#IC_102
napMD_MaintenanceFrequencyCode = {
    'RI_532'    :[u'continual',                u'continue',         u'continual'],
    'RI_533'    :[u'daily',                    u'quotidien',        u'P1D'],
    'RI_534'    :[u'weekly',                   u'hebdomadaire',     u'P1W'],
    'RI_535'    :[u'fortnightly',              u'quinzomadaire',    u'P2W'],
    'RI_536'    :[u'monthly',                  u'mensuel',          u'P1M'],
    'RI_537'    :[u'quarterly',                u'trimestriel',      u'P3M'],
    'RI_538'    :[u'biannually',               u'semestriel',       u'P6M'],
    'RI_539'    :[u'annually',                 u'annuel',           u'P1Y'],
    'RI_540'    :[u'asNeeded',                 u'auBesoin',         u'as_needed'],
    'RI_541'    :[u'irregular',                u'irrégulier',       u'irregular'],
    'RI_542'    :[u'notPlanned',               u'nonPlanifié',      u'not_planned'],
    'RI_543'    :[u'unknown',                  u'inconnu',          u'unknown'],
    'RI_544'    :[u'semimonthly',              u'bimensuel',        u'P2M'],
}

# # In the mapping doc but not used
# presentationForm
# IC_89    http://nap.geogratis.gc.ca/metadata/register/registerItemClasses-eng.html#IC_89
# presentationForm = {
#    'RI_387'    : [u'documentDigital',            u'documentNumérique'],
#    'RI_388'    : [u'documentHardcopy',            u'documentPapier'],
#    'RI_389'    : [u'imageDigital',                u'imageNumérique'],
#    'RI_390'    : [u'imageHardcopy',                u'imagePapier'],
#    'RI_391'    : [u'mapDigital',                u'carteNumérique'],
#    'RI_392'    : [u'mapHardcopy',                u'cartePapier'],
#    'RI_393'    : [u'modelDigital',                u'modèleNumérique'],
#    'RI_394'    : [u'modelHardcopy',                u'maquette'],
#    'RI_395'    : [u'profileDigital',            u'profilNumérique'],
#    'RI_396'    : [u'profileHardcopy',            u'profilPapier'],
#    'RI_397'    : [u'tableDigital',                u'tableNumérique'],
#    'RI_398'    : [u'tableHardcopy',                u'tablePapier'],
#    'RI_399'    : [u'videoDigital',                u'vidéoNumérique'],
#    'RI_400'    : [u'videoHardcopy',                u'vidéoFilm'],
#    'RI_401'    : [u'audioDigital',                u'audioNumérique'],
#    'RI_402'    : [u'audioHardcopy',                u'audioAnalogique'],
#    'RI_403'    : [u'multimediaDigital',            u'multimédiaNumérique'],
#    'RI_404'    : [u'multimediaHardcopy',        u'multimédiaAnalogique'],
#    'RI_405'    : [u'diagramDigital',            u'diagrammeNumérique'],
#    'RI_406'    : [u'diagramHardcopy',            u'diagrammePapier']
# }

napMD_KeywordTypeCode = {
    'farming'                                : [u'farming',                              u'Farming',                                  u'Agriculture'],
    'biota'                                  : [u'biota',                                u'Biota',                                    u'Biote'],
    'boundaries'                             : [u'boundaries',                           u'Boundaries',                               u'Frontières'],
    'climatologyMeteorologyAtmosphere'       : [u'climatology_meterology_atmosphere',    u'Climatology / Meteorology / Atmosphere',   u'Climatologie / Météorologie / Atmosphère'],
    'economy'                                : [u'economy',                              u'Economy',                                  u'Économie'],
    'elevation'                              : [u'elevation',                            u'Elevation',                                u'Élévation'],
    'environment'                            : [u'environment',                          u'Environment',                              u'Environnement'],
    'geoscientificInformation'               : [u'geoscientific_information',            u'Geoscientific Information',                u'Information géoscientifique'],
    'health'                                 : [u'health',                               u'Health',                                   u'Santé'],
    'imageryBaseMapsEarthCover'              : [u'imagery_base_maps_earth_cover',        u'Imagery Base Maps Earth Cover',            u'Imagerie carte de base couverture terrestre'],
    'intelligenceMilitary'                   : [u'intelligence_military',                u'Intelligence Military',                    u'Renseignements militaires'],
    'inlandWaters'                           : [u'inland_waters',                        u'Inland Waters',                            u'Eaux intérieures'],
    'location'                               : [u'location',                             u'Location',                                 u'Localisation'],
    'oceans'                                 : [u'oceans',                               u'Oceans',                                   u'Océans'],
    'planningCadastre'                       : [u'planning_cadastre',                    u'Planning Cadastre',                        u'Aménagement cadastre'],
    'society'                                : [u'society',                              u'Society',                                  u'Société'],
    'structure'                              : [u'structure',                            u'Structure',                                u'Structures'],
    'transportation'                         : [u'transport',                            u'Transportation',                           u'Transport'],
    'utilitiesCommunication'                 : [u'utilities_communication',              u'Utilities Communication',                  u'Services communication'],
    # French Equivalents
    'agriculture'                            : [u'farming',                              u'Farming',                                  u'Agriculture'],
    'biote'                                  : [u'biota',                                u'Biota',                                    u'Biote'],
    'frontières'                             : [u'boundaries',                           u'Boundaries',                               u'Frontières'],
    'limatologieMétéorologieAtmosphère'      : [u'climatology_meterology_atmosphere',    u'Climatology / Meteorology / Atmosphere',   u'Climatologie / Météorologie / Atmosphère'],
    'économie'                               : [u'economy',                              u'Economy',                                  u'Économie'],
    'élévation'                              : [u'elevation',                            u'Elevation',                                u'Élévation'],
    'environnement'                          : [u'environment',                          u'Environment',                              u'Environnement'],
    'informationGéoscientifique'             : [u'geoscientific_information',            u'Geoscientific Information',                u'Information géoscientifique'],
    'santé'                                  : [u'health',                               u'Health',                                   u'Santé'],
    'imagerieCarteDeBaseCouvertureTerrestre' : [u'imagery_base_maps_earth_cover',        u'Imagery Base Maps Earth Cover',            u'Imagerie carte de base couverture terrestre'],
    'renseignementsMilitaires'               : [u'intelligence_military',                u'Intelligence Military',                    u'Renseignements militaires'],
    'eauxIntérieures'                        : [u'inland_waters',                        u'Inland Waters',                            u'Eaux intérieures'],
    'localisation'                           : [u'location',                             u'Location',                                 u'Localisation'],
    'océans'                                 : [u'oceans',                               u'Oceans',                                   u'Océans'],
    'aménagementCadastre'                    : [u'planning_cadastre',                    u'Planning Cadastre',                        u'Aménagement cadastre'],
    'société'                                : [u'society',                              u'Society',                                  u'Société'],
    'structures'                             : [u'structure',                            u'Structure',                                u'Structures'],
    'transport'                              : [u'transport',                            u'Transportation',                           u'Transport'],
    'servicesCommunication'                  : [u'utilities_communication',              u'Utilities Communication',                  u'Services communication']
}

GC_Registry_of_Applied_Terms = {
    'Aboriginal Affairs and Northern Development Canada'        : [u'Aboriginal Affairs and Northern Development Canada',u'AANDC',u'Affaires autochtones et Développement du Nord Canada',u'AADNC',u'249'],
    'Affaires autochtones et Développement du Nord Canada'      : [u'Aboriginal Affairs and Northern Development Canada',u'AANDC',u'Affaires autochtones et Développement du Nord Canada',u'AADNC',u'249'],
    'Affaires autochtones et du Nord Canada'                    : [u'Aboriginal Affairs and Northern Development Canada',u'AANDC',u'Affaires autochtones et Développement du Nord Canada',u'AADNC',u'249'],
    'Indigenous and Northern Affairs Canada'                    : [u'Aboriginal Affairs and Northern Development Canada',u'AANDC',u'Affaires autochtones et Développement du Nord Canada',u'AADNC',u'249'],
    # 'Affaires autochtones et du Nord Canada'                  : [u'Indigenous and Northern Affairs Canada',u'INAC',u'Affaires autochtones et du Nord Canada',u'AANC',u'249'],
    # 'Indigenous and Northern Affairs Canada'                  : [u'Indigenous and Northern Affairs Canada',u'INAC',u'Affaires autochtones et du Nord Canada',u'AANC',u'249'],
    'Crown-Indigenous Relations and Northern Affairs Canada'    : [u'Crown-Indigenous Relations and Northern Affairs Canada',u'AANDC',u'Relations Couronne-Autochtones et Affaires du Nord Canada',u'AADNC',u'249'],
    'Relations Couronne-Autochtones et Affaires du Nord Canada' : [u'Crown-Indigenous Relations and Northern Affairs Canada',u'AANDC',u'Relations Couronne-Autochtones et Affaires du Nord Canada',u'AADNC',u'249'],

    'Environment Canada'                                        : [u'Environment Canada',u'EC',u'Environnement Canada',u'EC',u'99'],
    'Environnement Canada'                                      : [u'Environment Canada',u'EC',u'Environnement Canada',u'EC',u'99'],
    'Environment and Climate Change Canada'                     : [u'Environment Canada',u'EC',u'Environnement Canada',u'EC',u'99'],
    'Environnement et Changement climatique Canada'             : [u'Environment Canada',u'EC',u'Environnement Canada',u'EC',u'99'],
    # 'Environment and Climate Change Canada'                   : [u'Environment and Climate Change Canada',u'ECCC',u'Environnement et Changement climatique Canada',u'ECCC',u'99'],
    # 'Environnement et Changement climatique Canada'           : [u'Environment and Climate Change Canada',u'ECCC',u'Environnement et Changement climatique Canada',u'ECCC',u'99'],

    'Foreign Affairs and International Trade Canada'            : [u'Foreign Affairs and International Trade Canada',u'DFAIT',u'Affaires étrangères et Commerce international Canada',u'MAECI',u'64'],
    'Affaires étrangères et Commerce international Canada'      : [u'Foreign Affairs and International Trade Canada',u'DFAIT',u'Affaires étrangères et Commerce international Canada',u'MAECI',u'64'],
    'Affaires mondiales Canada'                                 : [u'Foreign Affairs and International Trade Canada',u'DFAIT',u'Affaires étrangères et Commerce international Canada',u'MAECI',u'64'],
    'Global Affairs Canada'                                     : [u'Foreign Affairs and International Trade Canada',u'DFAIT',u'Affaires étrangères et Commerce international Canada',u'MAECI',u'64'],
    # 'Affaires mondiales Canada'                               : [u'Global Affairs Canada',u'GAC',u'Affaires mondiales Canada',u'AMC',u'64'],
    # 'Global Affairs Canada'                                   : [u'Global Affairs Canada',u'GAC',u'Affaires mondiales Canada',u'AMC',u'64'],

    'Travaux publics et Services gouvernementaux Canada'        : [u'Public Works and Government Services Canada',u'PWGSC',u'Travaux publics et Services gouvernementaux Canada',u'TPSGC',u'81'],
    'Public Works and Government Services Canada'               : [u'Public Works and Government Services Canada',u'PWGSC',u'Travaux publics et Services gouvernementaux Canada',u'TPSGC',u'81'],
    'Public Services and Procurement Canada'                    : [u'Public Works and Government Services Canada',u'PWGSC',u'Travaux publics et Services gouvernementaux Canada',u'TPSGC',u'81'],
    'Services publics et Approvisionnement Canada'              : [u'Public Works and Government Services Canada',u'PWGSC',u'Travaux publics et Services gouvernementaux Canada',u'TPSGC',u'81'],
    # 'Public Services and Procurement Canada'                  : [u'Public Services and Procurement Canada',u'PSPC',u'Services publics et Approvisionnement Canada',u'SPAC',u'81'],
    # 'Services publics et Approvisionnement Canada'            : [u'Public Services and Procurement Canada',u'PSPC',u'Services publics et Approvisionnement Canada',u'SPAC',u'81'],

    'Industry Canada'                                           : [u'Industry Canada',u'IC',u'Industrie Canada',u'IC',u'230'],
    'Industrie Canada'                                          : [u'Industry Canada',u'IC',u'Industrie Canada',u'IC',u'230'],
    'Innovation, Science and Economic Development Canada'       : [u'Industry Canada',u'IC',u'Industrie Canada',u'IC',u'230'],
    'Innovation, Sciences et Développement économique Canada'   : [u'Industry Canada',u'IC',u'Industrie Canada',u'IC',u'230'],
    # 'Innovation                                               , Science and Economic Development Canada'                                                                                                                                                    : [u'Innovation, Science and Economic Development Canada',u'ISED',u'Innovation, Sciences et Développement économique Canada',u'ISDE',u'230'],
    # 'Innovation                                               , Sciences et Développement économique Canada'                                                                                                                                                    : [u'Innovation, Science and Economic Development Canada',u'ISED',u'Innovation, Sciences et Développement économique Canada',u'ISDE',u'230'],

    'Citizenship and Immigration Canada'                        : [u'Citizenship and Immigration Canada',u'CIC',u'Citoyenneté et Immigration Canada',u'CIC',u'94'],
    'Citoyenneté et Immigration Canada'                         : [u'Citizenship and Immigration Canada',u'CIC',u'Citoyenneté et Immigration Canada',u'CIC',u'94'],
    'Immigration, Refugees and Citizenship Canada'              : [u'Citizenship and Immigration Canada',u'CIC',u'Citoyenneté et Immigration Canada',u'CIC',u'94'],
    'Immigration, Réfugiés et Citoyenneté Canada'               : [u'Citizenship and Immigration Canada',u'CIC',u'Citoyenneté et Immigration Canada',u'CIC',u'94'],
    # 'Immigration                                              , Refugees and Citizenship Canada'                                                                                                                  : [u'Immigration, Refugees and Citizenship Canada',u'IRCC',u'Immigration, Réfugiés et Citoyenneté Canada',u'IRCC',u'94'],
    # 'Immigration                                              , Réfugiés et Citoyenneté Canada'                                                                                                                                                   : [u'Immigration, Refugees and Citizenship Canada',u'IRCC',u'Immigration, Réfugiés et Citoyenneté Canada',u'IRCC',u'94'],


    'Administration de pilotage de l\'Atlantique Canada'                                                                                                            : [u'Atlantic Pilotage Authority Canada',u'APA',u'Administration de pilotage de l\'Atlantique Canada',u'APA',u'221'],
    'Agence canadienne d\'inspection des aliments'                                                                                                                  : [u'Canadian Food Inspection Agency',u'CFIA',u'Agence canadienne d\'inspection des aliments',u'ACIA',u'206'],
    'Agence canadienne d\'évaluation environnementale'                                                                                                              : [u'Canadian Environmental Assessment Agency',u'CEAA',u'Agence canadienne d\'évaluation environnementale',u'ACEE',u'270'],
    'Agence canadienne pour l\'incitation à la réduction des émissions'                                                                                             : [u'Canada Emission Reduction Incentives Agency',u'',u'Agence canadienne pour l\'incitation à la réduction des émissions',u'',u'277'],
    'Agence fédérale de développement économique pour le Sud de l\'Ontario'                                                                                         : [u'Federal Economic Development Agency for Southern Ontario',u'FedDev Ontario',u'Agence fédérale de développement économique pour le Sud de l\'Ontario',u'FedDev Ontario',u'21'],
    'Centre canadien d\'hygiène et de sécurité au travail'                                                                                                          : [u'Canadian Centre for Occupational Health and Safety',u'CCOHS',u'Centre canadien d\'hygiène et de sécurité au travail',u'CCHST',u'35'],
    'Centre d\'analyse des opérations et déclarations financières du Canada'                                                                                        : [u'Financial Transactions and Reports Analysis Centre of Canada',u'FINTRAC',u'Centre d\'analyse des opérations et déclarations financières du Canada',u'CANAFE',u'127'],
    'Comité externe d\'examen de la GRC'                                                                                                                            : [u'RCMP External Review Committee',u'ERC',u'Comité externe d\'examen de la GRC',u'CEE',u'232'],
    'Comité externe d\'examen des griefs militaires'                                                                                                                : [u'Military Grievances External Review Committee',u'MGERC',u'Comité externe d\'examen des griefs militaires',u'CEEGM',u'43'],
    'Commissariat à l\'intégrité du secteur public du Canada'                                                                                                       : [u'Office of the Public Sector Integrity Commissioner of Canada',u'PSIC',u'Commissariat à l\'intégrité du secteur public du Canada',u'ISPC',u'210'],
    'Commission d\'examen des plaintes concernant la police militaire du Canada'                                                                                    : [u'Military Police Complaints Commission of Canada',u'MPCC',u'Commission d\'examen des plaintes concernant la police militaire du Canada',u'CPPM',u'66'],
    'Commission de l\'assurance-emploi du Canada'                                                                                                                   : [u'Canada Employment Insurance Commission',u'CEIC',u'Commission de l\'assurance-emploi du Canada',u'CAEC',u'196'],
    'Commission de l\'immigration et du statut de réfugié du Canada'                                                                                                : [u'Immigration and Refugee Board of Canada',u'IRB',u'Commission de l\'immigration et du statut de réfugié du Canada',u'CISR',u'5'],
    'Commission du droit d\'auteur Canada'                                                                                                                          : [u'Copyright Board Canada',u'CB',u'Commission du droit d\'auteur Canada',u'CDA',u'116'],
    'Conseil d\'examen du prix des médicaments brevetés Canada'                                                                                                     : [u'Patented Medicine Prices Review Board Canada',u'',u'Conseil d\'examen du prix des médicaments brevetés Canada',u'',u'15'],
    'Diversification de l\'économie de l\'Ouest Canada'                                                                                                             : [u'Western Economic Diversification Canada',u'WD',u'Diversification de l\'économie de l\'Ouest Canada',u'DEO',u'55'],
    'L\'Enquêteur correctionnel Canada'                                                                                                                             : [u'The Correctional Investigator Canada',u'OCI',u'L\'Enquêteur correctionnel Canada',u'BEC',u'5555'],
    'Musée canadien de l\'histoire'                                                                                                                                 : [u'Canadian Museum of History',u'CMH',u'Musée canadien de l\'histoire',u'MCH',u'263'],
    'Musée canadien de l\'immigration du Quai 21'                                                                                                                   : [u'Canadian Museum of Immigration at Pier 21',u'CMIP',u'Musée canadien de l\'immigration du Quai 21',u'MCIQ',u'2'],
    'Office de commercialisation du poisson d\'eau douce'                                                                                                           : [u'Freshwater Fish Marketing Corporation',u'FFMC',u'Office de commercialisation du poisson d\'eau douce',u'OCPED',u'252'],
    'Office national de l\'énergie'                                                                                                                                 : [u'National Energy Board',u'NEB',u'Office national de l\'énergie',u'ONE',u'239'],
    'Registraire de la Cour suprême du Canada et le secteur de l\'administration publique fédérale nommé en vertu du paragraphe 12(2) de la Loi sur la Cour suprême': [u'Registrar of the Supreme Court of Canada and that portion of the federal public administration appointed under subsection 12(2) of the Supreme Court Act',u'SCC',u'Registraire de la Cour suprême du Canada et le secteur de l\'administration publique fédérale nommé en vertu du paragraphe 12(2) de la Loi sur la Cour suprême',u'CSC',u'63'],
    'Service canadien d\'appui aux tribunaux administratifs'                                                                                                        : [u'Administrative Tribunals Support Service of Canada',u'ATSSC',u'Service canadien d\'appui aux tribunaux administratifs',u'SCDATA',u'8888888'],
    'Société canadienne d\'hypothèques et de logement'                                                                                                              : [u'Canada Mortgage and Housing Corporation',u'CMHC',u'Société canadienne d\'hypothèques et de logement',u'SCHL',u'87'],
    'Société d\'assurance-dépôts du Canada'                                                                                                                         : [u'Canada Deposit Insurance Corporation',u'CDIC',u'Société d\'assurance-dépôts du Canada',u'SADC',u'273'],
    'Société d\'expansion du Cap-Breton'                                                                                                                            : [u'Enterprise Cape Breton Corporation',u'',u'Société d\'expansion du Cap-Breton',u'',u'203'],
    'Tribunal d\'appel des transports du Canada'                                                                                                                    : [u'Transportation Appeal Tribunal of Canada',u'TATC',u'Tribunal d\'appel des transports du Canada',u'TATC',u'96'],
    'Énergie atomique du Canada'                                                                                                                                    : [u'Limitée',u'Atomic Energy of Canada Limited',u'',u'Énergie atomique du Canada',u'Limitée',u'',u'138'],
    'Administration canadienne de la sûreté du transport aérien'                                                                                                    : [u'Canadian Air Transport Security Authority',u'CATSA',u'Administration canadienne de la sûreté du transport aérien',u'ACSTA',u'250'],
    'Administration de pilotage des Grands Lacs Canada'                                                                                                             : [u'Great Lakes Pilotage Authority Canada',u'GLPA',u'Administration de pilotage des Grands Lacs Canada',u'APGL',u'261'],
    'Administration de pilotage des Laurentides Canada'                                                                                                             : [u'Laurentian Pilotage Authority Canada',u'LPA',u'Administration de pilotage des Laurentides Canada',u'APL',u'213'],
    'Administration de pilotage du Pacifique Canada'                                                                                                                : [u'Pacific Pilotage Authority Canada',u'PPA',u'Administration de pilotage du Pacifique Canada',u'APP',u'165'],
    'Administration du pipe-line du Nord Canada'                                                                                                                    : [u'Northern Pipeline Agency Canada',u'NPA',u'Administration du pipe-line du Nord Canada',u'APN',u'10'],
    'Administrative Tribunals Support Service of Canada'                                                                                                            : [u'Administrative Tribunals Support Service of Canada',u'ATSSC',u'Service canadien d\'appui aux tribunaux administratifs',u'SCDATA',u'8888888'],
    'Agence canadienne de développement économique du Nord'                                                                                                         : [u'Canadian Northern Economic Development Agency',u'CanNor',u'Agence canadienne de développement économique du Nord',u'CanNor',u'4'],
    'Agence de développement économique du Canada pour les régions du Québec'                                                                                        : [u'Economic Development Agency of Canada for the Regions of Quebec',u'CED',u'Agence de développement économique du Canada pour les régions du Québec',u'DEC',u'93'],
    'Agence de la consommation en matière financière du Canada'                                                                                                      : [u'Financial Consumer Agency of Canada',u'FCAC',u'Agence de la consommation en matière financière du Canada',u'ACFC',u'224'],
    'Agence de la santé publique du Canada'                                                                                                                          : [u'Public Health Agency of Canada',u'PHAC',u'Agence de la santé publique du Canada',u'ASPC',u'135'],
    'Agence de promotion économique du Canada atlantique'                                                                                                            : [u'Atlantic Canada Opportunities Agency',u'ACOA',u'Agence de promotion économique du Canada atlantique',u'APECA',u'276'],
    'Agence des services frontaliers du Canada'                                                                                                                      : [u'Canada Border Services Agency',u'CBSA',u'Agence des services frontaliers du Canada',u'ASFC',u'229'],
    'Agence du revenu du Canada'                                                                                                                                     : [u'Canada Revenue Agency',u'CRA',u'Agence du revenu du Canada',u'ARC',u'47'],
    'Agence spatiale canadienne'                                                                                                                                     : [u'Canadian Space Agency',u'CSA',u'Agence spatiale canadienne',u'ASC',u'3'],
    'Agriculture and Agri-Food Canada'                                                                                                                               : [u'Agriculture and Agri-Food Canada',u'AAFC',u'Agriculture et Agroalimentaire Canada',u'AAC',u'235'],
    'Agriculture et Agroalimentaire Canada'                                                                                                                          : [u'Agriculture and Agri-Food Canada',u'AAFC',u'Agriculture et Agroalimentaire Canada',u'AAC',u'235'],
    'Anciens Combattants Canada'                                                                                                                                     : [u'Veterans Affairs Canada',u'VAC',u'Anciens Combattants Canada',u'ACC',u'189'],
    'Atlantic Canada Opportunities Agency'                                                                                                                           : [u'Atlantic Canada Opportunities Agency',u'ACOA',u'Agence de promotion économique du Canada atlantique',u'APECA',u'276'],
    'Atlantic Pilotage Authority Canada'                                                                                                                             : [u'Atlantic Pilotage Authority Canada',u'APA',u'Administration de pilotage de l\'Atlantique Canada',u'APA',u'221'],
    'Atomic Energy of Canada Limited'                                                                                                                                : [u'Atomic Energy of Canada Limited',u'',u'Énergie atomique du Canada',u'Limitée',u'',u'138'],
    'Autorité du pont Windsor-Détroit'                                                                                                                               : [u'Windsor-Detroit Bridge Authority',u'',u'Autorité du pont Windsor-Détroit',u'',u'55553'],
    'Banque de développement du Canada'                                                                                                                              : [u'Business Development Bank of Canada',u'BDC',u'Banque de développement du Canada',u'BDC',u'150'],
    'Bibliothèque du Parlement'                                                                                                                                      : [u'Library of Parliament',u'LP',u'Bibliothèque du Parlement',u'BP',u'55555'],
    'Bibliothèque et Archives Canada'                                                                                                                                : [u'Library and Archives Canada',u'LAC',u'Bibliothèque et Archives Canada',u'BAC',u'129'],
    'Bureau de la sécurité des transports du Canada'                                                                                                                 : [u'Transportation Safety Board of Canada',u'TSB',u'Bureau de la sécurité des transports du Canada',u'BST',u'215'],
    'Bureau du commissaire du Centre de la sécurité des télécommunications'                                                                                          : [u'Office of the Communications Security Establishment Commissioner',u'OCSEC',u'Bureau du commissaire du Centre de la sécurité des télécommunications',u'BCCST',u'279'],
    'Bureau du Conseil privé'                                                                                                                                        : [u'Privy Council Office',u'',u'Bureau du Conseil privé',u'',u'173'],
    'Bureau du secrétaire du gouverneur général'                                                                                                                     : [u'Office of the Secretary to the Governor General',u'OSGG',u'Bureau du secrétaire du gouverneur général',u'BSGG',u'5557'],
    'Bureau du surintendant des institutions financières Canada'                                                                                                     : [u'Office of the Superintendent of Financial Institutions Canada',u'OSFI',u'Bureau du surintendant des institutions financières Canada',u'BSIF',u'184'],
    'Bureau du vérificateur général du Canada'                                                                                                                       : [u'Office of the Auditor General of Canada',u'OAG',u'Bureau du vérificateur général du Canada',u'BVG',u'125'],
    'Business Development Bank of Canada'                                                                                                                            : [u'Business Development Bank of Canada',u'BDC',u'Banque de développement du Canada',u'BDC',u'150'],
    'Canada Border Services Agency'                                                                                                                                  : [u'Canada Border Services Agency',u'CBSA',u'Agence des services frontaliers du Canada',u'ASFC',u'229'],
    'Canada Deposit Insurance Corporation'                                                                                                                           : [u'Canada Deposit Insurance Corporation',u'CDIC',u'Société d\'assurance-dépôts du Canada',u'SADC',u'273'],
    'Canada Development Investment Corporation'                                                                                                                      : [u'Canada Development Investment Corporation',u'CDEV',u'Corporation de développement des investissements du Canada',u'CDEV',u'148'],
    'Canada Emission Reduction Incentives Agency'                                                                                                                    : [u'Canada Emission Reduction Incentives Agency',u'',u'Agence canadienne pour l\'incitation à la réduction des émissions',u'',u'277'],
    'Canada Employment Insurance Commission'                                                                                                                         : [u'Canada Employment Insurance Commission',u'CEIC',u'Commission de l\'assurance-emploi du Canada',u'CAEC',u'196'],
    'Canada Industrial Relations Board'                                                                                                                              : [u'Canada Industrial Relations Board',u'CIRB',u'Conseil canadien des relations industrielles',u'CCRI',u'188'],
    'Canada Lands Company Limited'                                                                                                                                   : [u'Canada Lands Company Limited',u'',u'Société immobilière du Canada Limitée',u'',u'82'],
    'Canada Mortgage and Housing Corporation'                                                                                                                        : [u'Canada Mortgage and Housing Corporation',u'CMHC',u'Société canadienne d\'hypothèques et de logement',u'SCHL',u'87'],
    'Canada Post'                                                                                                                                                    : [u'Canada Post',u'CPC',u'Postes Canada',u'SCP',u'83'],
    'Canada Revenue Agency'                                                                                                                                          : [u'Canada Revenue Agency',u'CRA',u'Agence du revenu du Canada',u'ARC',u'47'],
    'Canada School of Public Service'                                                                                                                                : [u'Canada School of Public Service',u'CSPS',u'École de la fonction publique du Canada',u'EFPC',u'73'],
    'Canada Science and Technology Museum'                                                                                                                           : [u'Canada Science and Technology Museum',u'CSTM',u'Musée des sciences et de la technologie du Canada',u'MSTC',u'202'],
    'Canadian Air Transport Security Authority'                                                                                                                      : [u'Canadian Air Transport Security Authority',u'CATSA',u'Administration canadienne de la sûreté du transport aérien',u'ACSTA',u'250'],
    'Canadian Centre for Occupational Health and Safety'                                                                                                             : [u'Canadian Centre for Occupational Health and Safety',u'CCOHS',u'Centre canadien d\'hygiène et de sécurité au travail',u'CCHST',u'35'],
    'Canadian Commercial Corporation'                                                                                                                                : [u'Canadian Commercial Corporation',u'CCC',u'Corporation commerciale canadienne',u'CCC',u'34'],
    'Canadian Dairy Commission'                                                                                                                                      : [u'Canadian Dairy Commission',u'CDC',u'Commission canadienne du lait',u'CCL',u'151'],
    'Canadian Environmental Assessment Agency'                                                                                                                       : [u'Canadian Environmental Assessment Agency',u'CEAA',u'Agence canadienne d\'évaluation environnementale',u'ACEE',u'270'],
    'Canadian Food Inspection Agency'                                                                                                                                : [u'Canadian Food Inspection Agency',u'CFIA',u'Agence canadienne d\'inspection des aliments',u'ACIA',u'206'],
    'Canadian Grain Commission'                                                                                                                                      : [u'Canadian Grain Commission',u'CGC',u'Commission canadienne des grains',u'CCG',u'169'],
    'Canadian Heritage'                                                                                                                                              : [u'Canadian Heritage',u'PCH',u'Patrimoine canadien',u'PCH',u'16'],
    'Canadian Human Rights Commission'                                                                                                                               : [u'Canadian Human Rights Commission',u'CHRC',u'Commission canadienne des droits de la personne',u'CCDP',u'113'],
    'Canadian Institutes of Health Research'                                                                                                                         : [u'Canadian Institutes of Health Research',u'CIHR',u'Instituts de recherche en santé du Canada',u'IRSC',u'236'],
    'Canadian Intergovernmental Conference Secretariat'                                                                                                              : [u'Canadian Intergovernmental Conference Secretariat',u'CICS',u'Secrétariat des conférences intergouvernementales canadiennes',u'SCIC',u'274'],
    'Canadian International Trade Tribunal'                                                                                                                          : [u'Canadian International Trade Tribunal',u'CITT',u'Tribunal canadien du commerce extérieur',u'TCCE',u'175'],
    'Canadian Museum for Human Rights'                                                                                                                               : [u'Canadian Museum for Human Rights',u'CMHR',u'Musée canadien pour les droits de la personne',u'MCDP',u'267'],
    'Canadian Museum of History'                                                                                                                                     : [u'Canadian Museum of History',u'CMH',u'Musée canadien de l\'histoire',u'MCH',u'263'],
    'Canadian Museum of Immigration at Pier 21'                                                                                                                      : [u'Canadian Museum of Immigration at Pier 21',u'CMIP',u'Musée canadien de l\'immigration du Quai 21',u'MCIQ',u'2'],
    'Canadian Museum of Nature'                                                                                                                                      : [u'Canadian Museum of Nature',u'CMN',u'Musée canadien de la nature',u'MCN',u'57'],
    'Canadian Northern Economic Development Agency'                                                                                                                  : [u'Canadian Northern Economic Development Agency',u'CanNor',u'Agence canadienne de développement économique du Nord',u'CanNor',u'4'],
    'Canadian Nuclear Safety Commission'                                                                                                                             : [u'Canadian Nuclear Safety Commission',u'CNSC',u'Commission canadienne de sûreté nucléaire',u'CCSN',u'58'],
    'Canadian Polar Commission'                                                                                                                                      : [u'Canadian Polar Commission',u'POLAR',u'Commission canadienne des affaires polaires',u'POLAIRE',u'143'],
    'Canadian Radio-television and Telecommunications Commission'                                                                                                    : [u'Canadian Radio-television and Telecommunications Commission',u'CRTC',u'Conseil de la radiodiffusion et des télécommunications canadiennes',u'CRTC',u'126'],
    'Canadian Security Intelligence Service'                                                                                                                         : [u'Canadian Security Intelligence Service',u'CSIS',u'Service canadien du renseignement de sécurité',u'SCRS',u'90'],
    'Canadian Space Agency'                                                                                                                                          : [u'Canadian Space Agency',u'CSA',u'Agence spatiale canadienne',u'ASC',u'3'],
    'Canadian Transportation Agency'                                                                                                                                 : [u'Canadian Transportation Agency',u'CTA',u'Office des transports du Canada',u'OTC',u'124'],
    'Centre de la sécurité des télécommunications Canada'                                                                                                            : [u'Communications Security Establishment Canada',u'CSEC',u'Centre de la sécurité des télécommunications Canada',u'CSTC',u'156'],
    'Civilian Review and Complaints Commission for the RCMP'                                                                                                         : [u'Civilian Review and Complaints Commission for the RCMP',u'CRCC',u'Commission civile d’examen et de traitement des plaintes relatives à la GRC',u'CCETP',u'136'],
    'Comité de surveillance des activités de renseignement de sécurité'                                                                                              : [u'Security Intelligence Review Committee',u'SIRC',u'Comité de surveillance des activités de renseignement de sécurité',u'CSARS',u'109'],
    'Commissariat au lobbying du Canada'                                                                                                                             : [u'Office of the Commissioner of Lobbying of Canada',u'OCL',u'Commissariat au lobbying du Canada',u'CAL',u'205'],
    'Commissariat aux langues officielles'                                                                                                                           : [u'Office of the Commissioner of Official Languages',u'OCOL',u'Commissariat aux langues officielles',u'CLO',u'258'],
    'Commissariat à la magistrature fédérale Canada'                                                                                                                 : [u'Office of the Commissioner for Federal Judicial Affairs Canada',u'FJA',u'Commissariat à la magistrature fédérale Canada',u'CMF',u'140'],
    'Commissariats à l’information et à la protection de la vie privée au Canada'                                                                                    : [u'Offices of the Information and Privacy Commissioners of Canada',u'OIC',u'Commissariats à l’information et à la protection de la vie privée au Canada',u'CI',u'41'],
    'Commissariats à l’information et à la protection de la vie privée au Canada'                                                                                    : [u'Offices of the Information and Privacy Commissioners of Canada',u'OPC',u'Commissariats à l’information et à la protection de la vie privée au Canada',u'CPVP',u'226'],
    'Commission canadienne de sûreté nucléaire'                                                                                                                      : [u'Canadian Nuclear Safety Commission',u'CNSC',u'Commission canadienne de sûreté nucléaire',u'CCSN',u'58'],
    'Commission canadienne des affaires polaires'                                                                                                                    : [u'Canadian Polar Commission',u'POLAR',u'Commission canadienne des affaires polaires',u'POLAIRE',u'143'],
    'Commission canadienne des droits de la personne'                                                                                                                : [u'Canadian Human Rights Commission',u'CHRC',u'Commission canadienne des droits de la personne',u'CCDP',u'113'],
    'Commission canadienne des grains'                                                                                                                               : [u'Canadian Grain Commission',u'CGC',u'Commission canadienne des grains',u'CCG',u'169'],
    'Commission canadienne du lait'                                                                                                                                  : [u'Canadian Dairy Commission',u'CDC',u'Commission canadienne du lait',u'CCL',u'151'],
    'Commission civile d’examen et de traitement des plaintes relatives à la GRC'                                                                                    : [u'Civilian Review and Complaints Commission for the RCMP',u'CRCC',u'Commission civile d’examen et de traitement des plaintes relatives à la GRC',u'CCETP',u'136'],
    'Commission de la capitale nationale'                                                                                                                            : [u'National Capital Commission',u'NCC',u'Commission de la capitale nationale',u'CCN',u'22'],
    'Commission de la fonction publique du Canada'                                                                                                                   : [u'Public Service Commission of Canada',u'PSC',u'Commission de la fonction publique du Canada',u'CFP',u'227'],
    'Commission de vérité et de réconciliation relative aux pensionnats indiens'                                                                                     : [u'Indian Residential Schools Truth and Reconciliation Commission',u'',u'Commission de vérité et de réconciliation relative aux pensionnats indiens',u'',u'245'],
    'Commission des champs de bataille nationaux'                                                                                                                    : [u'The National Battlefields Commission',u'NBC',u'Commission des champs de bataille nationaux',u'CCBN',u'262'],
    'Commission des libérations conditionnelles du Canada'                                                                                                           : [u'Parole Board of Canada',u'PBC',u'Commission des libérations conditionnelles du Canada',u'CLCC',u'246'],
    'Commission des relations de travail dans la fonction publique'                                                                                                  : [u'Public Service Labour Relations Board',u'PSLRB',u'Commission des relations de travail dans la fonction publique',u'CRTFP',u'102'],
    'Commission du droit du Canada'                                                                                                                                  : [u'Law Commission of Canada',u'',u'Commission du droit du Canada',u'',u'231'],
    'Communications Security Establishment Canada'                                                                                                                   : [u'Communications Security Establishment Canada',u'CSEC',u'Centre de la sécurité des télécommunications Canada',u'CSTC',u'156'],
    'Condition féminine Canada'                                                                                                                                      : [u'Status of Women Canada',u'SWC',u'Condition féminine Canada',u'CFC',u'147'],
    'Conseil canadien des normes'                                                                                                                                    : [u'Standards Council of Canada',u'SCC-CCN',u'Conseil canadien des normes',u'SCC-CCN',u'107'],
    'Conseil canadien des relations industrielles'                                                                                                                   : [u'Canada Industrial Relations Board',u'CIRB',u'Conseil canadien des relations industrielles',u'CCRI',u'188'],
    'Conseil de la radiodiffusion et des télécommunications canadiennes'                                                                                             : [u'Canadian Radio-television and Telecommunications Commission',u'CRTC',u'Conseil de la radiodiffusion et des télécommunications canadiennes',u'CRTC',u'126'],
    'Conseil de recherches en sciences humaines du Canada'                                                                                                           : [u'Social Sciences and Humanities Research Council of Canada',u'SSHRC',u'Conseil de recherches en sciences humaines du Canada',u'CRSH',u'207'],
    'Conseil des produits agricoles du Canada'                                                                                                                       : [u'Farm Products Council of Canada',u'FPCC',u'Conseil des produits agricoles du Canada',u'CPAC',u'200'],
    'Conseil du Trésor'                                                                                                                                              : [u'Treasury Board',u'TB',u'Conseil du Trésor',u'CT',u'105'],
    'Conseil national de recherches Canada'                                                                                                                          : [u'National Research Council Canada',u'NRC',u'Conseil national de recherches Canada',u'CNRC',u'172'],
    'Construction de Défense Canada'                                                                                                                                 : [u'Defence Construction Canada',u'DCC',u'Construction de Défense Canada',u'CDC',u'28'],
    'Copyright Board Canada'                                                                                                                                         : [u'Copyright Board Canada',u'CB',u'Commission du droit d\'auteur Canada',u'CDA',u'116'],
    'Corporation commerciale canadienne'                                                                                                                             : [u'Canadian Commercial Corporation',u'CCC',u'Corporation commerciale canadienne',u'CCC',u'34'],
    'Corporation de développement des investissements du Canada'                                                                                                     : [u'Canada Development Investment Corporation',u'CDEV',u'Corporation de développement des investissements du Canada',u'CDEV',u'148'],
    'Correctional Service of Canada'                                                                                                                                 : [u'Correctional Service of Canada',u'CSC',u'Service correctionnel du Canada',u'SCC',u'193'],
    'Courts Administration Service'                                                                                                                                  : [u'Courts Administration Service',u'CAS',u'Service administratif des tribunaux judiciaires',u'SATJ',u'228'],
    'Defence Construction Canada'                                                                                                                                    : [u'Defence Construction Canada',u'DCC',u'Construction de Défense Canada',u'CDC',u'28'],
    'Department of Finance Canada'                                                                                                                                   : [u'Department of Finance Canada',u'FIN',u'Ministère des Finances Canada',u'FIN',u'157'],
    'Department of Justice Canada'                                                                                                                                   : [u'Department of Justice Canada',u'JUS',u'Ministère de la Justice Canada',u'JUS',u'119'],
    'Destination Canada'                                                                                                                                             : [u'Destination Canada',u'  DC',u'Destination Canada',u'  DC',u'178'],
    'Destination Canada'                                                                                                                                             : [u'Destination Canada',u'  DC',u'Destination Canada',u'  DC',u'178'],
    'Défense nationale'                                                                                                                                              : [u'National Defence',u'DND',u'Défense nationale',u'MDN',u'32'],
    'Economic Development Agency of Canada for the Regions of Quebec'                                                                                                : [u'Economic Development Agency of Canada for the Regions of Quebec',u'CED',u'Agence de développement économique du Canada pour les régions du Québec',u'DEC',u'93'],
    'Elections Canada'                                                                                                                                               : [u'Elections Canada',u'elections',u'Élections Canada',u'elections',u'285'],
    'Emploi et Développement social Canada'                                                                                                                          : [u'Employment and Social Development Canada',u'ESDC',u'Emploi et Développement social Canada',u'ESDC',u'141'],
    'Employment and Social Development Canada'                                                                                                                       : [u'Employment and Social Development Canada',u'ESDC',u'Emploi et Développement social Canada',u'ESDC',u'141'],
    'Enterprise Cape Breton Corporation'                                                                                                                             : [u'Enterprise Cape Breton Corporation',u'',u'Société d\'expansion du Cap-Breton',u'',u'203'],
    'Export Development Canada'                                                                                                                                      : [u'Export Development Canada',u'EDC',u'Exportation et développement Canada',u'EDC',u'62'],
    'Exportation et développement Canada'                                                                                                                            : [u'Export Development Canada',u'EDC',u'Exportation et développement Canada',u'EDC',u'62'],
    'Farm Credit Canada'                                                                                                                                             : [u'Farm Credit Canada',u'FCC',u'Financement agricole Canada',u'FAC',u'23'],
    'Farm Products Council of Canada'                                                                                                                                : [u'Farm Products Council of Canada',u'FPCC',u'Conseil des produits agricoles du Canada',u'CPAC',u'200'],
    'Federal Bridge Corporation'                                                                                                                                     : [u'Federal Bridge Corporation',u'FBCL',u'Société des ponts fédéraux',u'SPFL',u'254'],
    'Federal Economic Development Agency for Southern Ontario'                                                                                                       : [u'Federal Economic Development Agency for Southern Ontario',u'FedDev Ontario',u'Agence fédérale de développement économique pour le Sud de l\'Ontario',u'FedDev Ontario',u'21'],
    'Financement agricole Canada'                                                                                                                                    : [u'Farm Credit Canada',u'FCC',u'Financement agricole Canada',u'FAC',u'23'],
    'Financial Consumer Agency of Canada'                                                                                                                            : [u'Financial Consumer Agency of Canada',u'FCAC',u'Agence de la consommation en matière financière du Canada',u'ACFC',u'224'],
    'Financial Transactions and Reports Analysis Centre of Canada'                                                                                                   : [u'Financial Transactions and Reports Analysis Centre of Canada',u'FINTRAC',u'Centre d\'analyse des opérations et déclarations financières du Canada',u'CANAFE',u'127'],
    'Fisheries and Oceans Canada'                                                                                                                                    : [u'Fisheries and Oceans Canada',u'DFO',u'Pêches et Océans Canada',u'MPO',u'253'],
    'Freshwater Fish Marketing Corporation'                                                                                                                          : [u'Freshwater Fish Marketing Corporation',u'FFMC',u'Office de commercialisation du poisson d\'eau douce',u'OCPED',u'252'],
    'Gendarmerie royale du Canada'                                                                                                                                   : [u'Royal Canadian Mounted Police',u'RCMP',u'Gendarmerie royale du Canada',u'GRC',u'131'],
    'Great Lakes Pilotage Authority Canada'                                                                                                                          : [u'Great Lakes Pilotage Authority Canada',u'GLPA',u'Administration de pilotage des Grands Lacs Canada',u'APGL',u'261'],
    'Greffe du Tribunal de la concurrence'                                                                                                                           : [u'Registry of the Competition Tribunal',u'RCT',u'Greffe du Tribunal de la concurrence',u'GTC',u'89'],
    'Greffe du Tribunal des revendications particulières du Canada'                                                                                                  : [u'Registry of the Specific Claims Tribunal of Canada',u'SCT',u'Greffe du Tribunal des revendications particulières du Canada',u'TRP',u'220'],
    'Health Canada'                                                                                                                                                  : [u'Health Canada',u'HC',u'Santé Canada',u'SC',u'271'],
    'Human Rights Tribunal of Canada'                                                                                                                                : [u'Human Rights Tribunal of Canada',u'HRTC',u'Tribunal des droits de la personne du Canada',u'TDPC',u'164'],
    'Immigration and Refugee Board of Canada'                                                                                                                        : [u'Immigration and Refugee Board of Canada',u'IRB',u'Commission de l\'immigration et du statut de réfugié du Canada',u'CISR',u'5'],
    'Indian Residential Schools Truth and Reconciliation Commission'                                                                                                 : [u'Indian Residential Schools Truth and Reconciliation Commission',u'',u'Commission de vérité et de réconciliation relative aux pensionnats indiens',u'',u'245'],
    'Infrastructure Canada'                                                                                                                                          : [u'Infrastructure Canada',u'INFC',u'Infrastructure Canada',u'INFC',u'278'],
    'Infrastructure Canada'                                                                                                                                          : [u'Infrastructure Canada',u'INFC',u'Infrastructure Canada',u'INFC',u'278'],
    'Instituts de recherche en santé du Canada'                                                                                                                      : [u'Canadian Institutes of Health Research',u'CIHR',u'Instituts de recherche en santé du Canada',u'IRSC',u'236'],
    'Jacques Cartier and Champlain Bridges Incorporated'                                                                                                             : [u'Jacques Cartier and Champlain Bridges Incorporated',u'JCCBI',u'Les Ponts Jacques-Cartier et Champlain Incorporée',u'PJCCI',u'55559'],
    'Laurentian Pilotage Authority Canada'                                                                                                                           : [u'Laurentian Pilotage Authority Canada',u'LPA',u'Administration de pilotage des Laurentides Canada',u'APL',u'213'],
    'Law Commission of Canada'                                                                                                                                       : [u'Law Commission of Canada',u'',u'Commission du droit du Canada',u'',u'231'],
    'Les Ponts Jacques-Cartier et Champlain Incorporée'                                                                                                              : [u'Jacques Cartier and Champlain Bridges Incorporated',u'JCCBI',u'Les Ponts Jacques-Cartier et Champlain Incorporée',u'PJCCI',u'55559'],
    'Library and Archives Canada'                                                                                                                                    : [u'Library and Archives Canada',u'LAC',u'Bibliothèque et Archives Canada',u'BAC',u'129'],
    'Library of Parliament'                                                                                                                                          : [u'Library of Parliament',u'LP',u'Bibliothèque du Parlement',u'BP',u'55555'],
    'Marine Atlantic Inc.'                                                                                                                                           : [u'Marine Atlantic Inc.',u'',u'Marine Atlantique S.C.C.',u'',u'238'],
    'Marine Atlantique S.C.C.'                                                                                                                                       : [u'Marine Atlantic Inc.',u'',u'Marine Atlantique S.C.C.',u'',u'238'],
    'Military Grievances External Review Committee'                                                                                                                  : [u'Military Grievances External Review Committee',u'MGERC',u'Comité externe d\'examen des griefs militaires',u'CEEGM',u'43'],
    'Military Police Complaints Commission of Canada'                                                                                                                : [u'Military Police Complaints Commission of Canada',u'MPCC',u'Commission d\'examen des plaintes concernant la police militaire du Canada',u'CPPM',u'66'],
    'Ministère de la Justice Canada'                                                                                                                                 : [u'Department of Justice Canada',u'JUS',u'Ministère de la Justice Canada',u'JUS',u'119'],
    'Ministère des Finances Canada'                                                                                                                                  : [u'Department of Finance Canada',u'FIN',u'Ministère des Finances Canada',u'FIN',u'157'],
    'Monnaie royale canadienne'                                                                                                                                      : [u'Royal Canadian Mint',u'',u'Monnaie royale canadienne',u'',u'18'],
    'Musée canadien de la nature'                                                                                                                                    : [u'Canadian Museum of Nature',u'CMN',u'Musée canadien de la nature',u'MCN',u'57'],
    'Musée canadien pour les droits de la personne'                                                                                                                  : [u'Canadian Museum for Human Rights',u'CMHR',u'Musée canadien pour les droits de la personne',u'MCDP',u'267'],
    'Musée des beaux-arts du Canada'                                                                                                                                 : [u'National Gallery of Canada',u'NGC',u'Musée des beaux-arts du Canada',u'MBAC',u'59'],
    'Musée des sciences et de la technologie du Canada'                                                                                                              : [u'Canada Science and Technology Museum',u'CSTM',u'Musée des sciences et de la technologie du Canada',u'MSTC',u'202'],
    'National Capital Commission'                                                                                                                                    : [u'National Capital Commission',u'NCC',u'Commission de la capitale nationale',u'CCN',u'22'],
    'National Defence'                                                                                                                                               : [u'National Defence',u'DND',u'Défense nationale',u'MDN',u'32'],
    'National Energy Board'                                                                                                                                          : [u'National Energy Board',u'NEB',u'Office national de l\'énergie',u'ONE',u'239'],
    'National Film Board'                                                                                                                                            : [u'National Film Board',u'NFB',u'Office national du film',u'ONF',u'167'],
    'National Gallery of Canada'                                                                                                                                     : [u'National Gallery of Canada',u'NGC',u'Musée des beaux-arts du Canada',u'MBAC',u'59'],
    'National Research Council Canada'                                                                                                                               : [u'National Research Council Canada',u'NRC',u'Conseil national de recherches Canada',u'CNRC',u'172'],
    'Natural Resources Canada'                                                                                                                                       : [u'Natural Resources Canada',u'NRCan',u'Ressources naturelles Canada',u'RNCan',u'115'],
    'Northern Pipeline Agency Canada'                                                                                                                                : [u'Northern Pipeline Agency Canada',u'NPA',u'Administration du pipe-line du Nord Canada',u'APN',u'10'],
    'Office des transports du Canada'                                                                                                                                : [u'Canadian Transportation Agency',u'CTA',u'Office des transports du Canada',u'OTC',u'124'],
    'Office national du film'                                                                                                                                        : [u'National Film Board',u'NFB',u'Office national du film',u'ONF',u'167'],
    'Office of the Auditor General of Canada'                                                                                                                        : [u'Office of the Auditor General of Canada',u'OAG',u'Bureau du vérificateur général du Canada',u'BVG',u'125'],
    'Office of the Chief Electoral Officer'                                                                                                                          : [u'Office of the Chief Electoral Officer',u'elections',u'Bureau du directeur général des élections',u'elections',u'---'],
    'Bureau du directeur général des élections'                                                                                                                      : [u'Office of the Chief Electoral Officer',u'elections',u'Bureau du directeur général des élections',u'elections',u'---'],
    'Office of the Commissioner for Federal Judicial Affairs Canada'                                                                                                 : [u'Office of the Commissioner for Federal Judicial Affairs Canada',u'FJA',u'Commissariat à la magistrature fédérale Canada',u'CMF',u'140'],
    'Office of the Commissioner of Lobbying of Canada'                                                                                                               : [u'Office of the Commissioner of Lobbying of Canada',u'OCL',u'Commissariat au lobbying du Canada',u'CAL',u'205'],
    'Office of the Commissioner of Official Languages'                                                                                                               : [u'Office of the Commissioner of Official Languages',u'OCOL',u'Commissariat aux langues officielles',u'CLO',u'258'],
    'Office of the Communications Security Establishment Commissioner'                                                                                               : [u'Office of the Communications Security Establishment Commissioner',u'OCSEC',u'Bureau du commissaire du Centre de la sécurité des télécommunications',u'BCCST',u'279'],
    'Office of the Public Sector Integrity Commissioner of Canada'                                                                                                   : [u'Office of the Public Sector Integrity Commissioner of Canada',u'PSIC',u'Commissariat à l\'intégrité du secteur public du Canada',u'ISPC',u'210'],
    'Office of the Secretary to the Governor General'                                                                                                                : [u'Office of the Secretary to the Governor General',u'OSGG',u'Bureau du secrétaire du gouverneur général',u'BSGG',u'5557'],
    'Office of the Superintendent of Financial Institutions Canada'                                                                                                  : [u'Office of the Superintendent of Financial Institutions Canada',u'OSFI',u'Bureau du surintendant des institutions financières Canada',u'BSIF',u'184'],
    'Offices of the Information and Privacy Commissioners of Canada'                                                                                                 : [u'Offices of the Information and Privacy Commissioners of Canada',u'OIC',u'Commissariats à l’information et à la protection de la vie privée au Canada',u'CI',u'41'],
    'Offices of the Information and Privacy Commissioners of Canada'                                                                                                 : [u'Offices of the Information and Privacy Commissioners of Canada',u'OPC',u'Commissariats à l’information et à la protection de la vie privée au Canada',u'CPVP',u'226'],
    'Pacific Pilotage Authority Canada'                                                                                                                              : [u'Pacific Pilotage Authority Canada',u'PPA',u'Administration de pilotage du Pacifique Canada',u'APP',u'165'],
    'Parcs Canada'                                                                                                                                                   : [u'Parks Canada',u'PC',u'Parcs Canada',u'PC',u'154'],
    'Parks Canada'                                                                                                                                                   : [u'Parks Canada',u'PC',u'Parcs Canada',u'PC',u'154'],
    'Parole Board of Canada'                                                                                                                                         : [u'Parole Board of Canada',u'PBC',u'Commission des libérations conditionnelles du Canada',u'CLCC',u'246'],
    'Patented Medicine Prices Review Board Canada'                                                                                                                   : [u'Patented Medicine Prices Review Board Canada',u'',u'Conseil d\'examen du prix des médicaments brevetés Canada',u'',u'15'],
    'Patrimoine canadien'                                                                                                                                            : [u'Canadian Heritage',u'PCH',u'Patrimoine canadien',u'PCH',u'16'],
    'Postes Canada'                                                                                                                                                  : [u'Canada Post',u'CPC',u'Postes Canada',u'SCP',u'83'],
    'Privy Council Office'                                                                                                                                           : [u'Privy Council Office',u'',u'Bureau du Conseil privé',u'',u'173'],
    'Public Health Agency of Canada'                                                                                                                                 : [u'Public Health Agency of Canada',u'PHAC',u'Agence de la santé publique du Canada',u'ASPC',u'135'],
    'Public Prosecution Service of Canada'                                                                                                                           : [u'Public Prosecution Service of Canada',u'PPSC',u'Service des poursuites pénales du Canada',u'SPPC',u'98'],
    'Public Safety Canada'                                                                                                                                           : [u'Public Safety Canada',u'PS',u'Sécurité publique Canada',u'SP',u'214'],
    'Public Servants Disclosure Protection Tribunal Canada'                                                                                                          : [u'Public Servants Disclosure Protection Tribunal Canada',u'PSDPTC',u'Tribunal de la protection des fonctionnaires divulgateurs Canada',u'TPFDC',u'40'],
    'Public Service Commission of Canada'                                                                                                                            : [u'Public Service Commission of Canada',u'PSC',u'Commission de la fonction publique du Canada',u'CFP',u'227'],
    'Public Service Labour Relations Board'                                                                                                                          : [u'Public Service Labour Relations Board',u'PSLRB',u'Commission des relations de travail dans la fonction publique',u'CRTFP',u'102'],
    'Public Service Staffing Tribunal'                                                                                                                               : [u'Public Service Staffing Tribunal',u'PSST',u'Tribunal de la dotation de la fonction publique',u'TDFP',u'266'],
    'Pêches et Océans Canada'                                                                                                                                        : [u'Fisheries and Oceans Canada',u'DFO',u'Pêches et Océans Canada',u'MPO',u'253'],
    'RCMP External Review Committee'                                                                                                                                 : [u'RCMP External Review Committee',u'ERC',u'Comité externe d\'examen de la GRC',u'CEE',u'232'],
    'Recherches en sciences et en génie Canada'                                                                                                                      : [u'Science and Engineering Research Canada',u'SERC',u'Recherches en sciences et en génie Canada',u'RSGC',u'110'],
    'Registrar of the Supreme Court of Canada and that portion of the federal public administration appointed under subsection 12(2) of the Supreme Court Act'       : [u'Registrar of the Supreme Court of Canada and that portion of the federal public administration appointed under subsection 12(2) of the Supreme Court Act',u'SCC',u'Registraire de la Cour suprême du Canada et le secteur de l\'administration publique fédérale nommé en vertu du paragraphe 12(2) de la Loi sur la Cour suprême',u'CSC',u'63'],
    'Registry of the Competition Tribunal'                                                                                                                           : [u'Registry of the Competition Tribunal',u'RCT',u'Greffe du Tribunal de la concurrence',u'GTC',u'89'],
    'Registry of the Specific Claims Tribunal of Canada'                                                                                                             : [u'Registry of the Specific Claims Tribunal of Canada',u'SCT',u'Greffe du Tribunal des revendications particulières du Canada',u'TRP',u'220'],
    'Ressources naturelles Canada'                                                                                                                                   : [u'Natural Resources Canada',u'NRCan',u'Ressources naturelles Canada',u'RNCan',u'115'],
    'Ridley Terminals Inc.'                                                                                                                                          : [u'Ridley Terminals Inc.',u'',u'Ridley Terminals Inc.',u'',u'142'],
    'Ridley Terminals Inc.'                                                                                                                                          : [u'Ridley Terminals Inc.',u'',u'Ridley Terminals Inc.',u'',u'142'],
    'Royal Canadian Mint'                                                                                                                                            : [u'Royal Canadian Mint',u'',u'Monnaie royale canadienne',u'',u'18'],
    'Royal Canadian Mounted Police'                                                                                                                                  : [u'Royal Canadian Mounted Police',u'RCMP',u'Gendarmerie royale du Canada',u'GRC',u'131'],
    'Santé Canada'                                                                                                                                                   : [u'Health Canada',u'HC',u'Santé Canada',u'SC',u'271'],
    'Science and Engineering Research Canada'                                                                                                                        : [u'Science and Engineering Research Canada',u'SERC',u'Recherches en sciences et en génie Canada',u'RSGC',u'110'],
    'Secrétariat des conférences intergouvernementales canadiennes'                                                                                                  : [u'Canadian Intergovernmental Conference Secretariat',u'CICS',u'Secrétariat des conférences intergouvernementales canadiennes',u'SCIC',u'274'],
    'Secrétariat du Conseil du Trésor du Canada'                                                                                                                     : [u'Treasury Board of Canada Secretariat',u'TBS',u'Secrétariat du Conseil du Trésor du Canada',u'SCT',u'139'],
    'Security Intelligence Review Committee'                                                                                                                         : [u'Security Intelligence Review Committee',u'SIRC',u'Comité de surveillance des activités de renseignement de sécurité',u'CSARS',u'109'],
    'Service administratif des tribunaux judiciaires'                                                                                                                : [u'Courts Administration Service',u'CAS',u'Service administratif des tribunaux judiciaires',u'SATJ',u'228'],
    'Service canadien du renseignement de sécurité'                                                                                                                  : [u'Canadian Security Intelligence Service',u'CSIS',u'Service canadien du renseignement de sécurité',u'SCRS',u'90'],
    'Service correctionnel du Canada'                                                                                                                                : [u'Correctional Service of Canada',u'CSC',u'Service correctionnel du Canada',u'SCC',u'193'],
    'Service des poursuites pénales du Canada'                                                                                                                       : [u'Public Prosecution Service of Canada',u'PPSC',u'Service des poursuites pénales du Canada',u'SPPC',u'98'],
    'Services partagés Canada'                                                                                                                                       : [u'Shared Services Canada',u'SSC',u'Services partagés Canada',u'SPC',u'92'],
    'Shared Services Canada'                                                                                                                                         : [u'Shared Services Canada',u'SSC',u'Services partagés Canada',u'SPC',u'92'],
    'Social Sciences and Humanities Research Council of Canada'                                                                                                      : [u'Social Sciences and Humanities Research Council of Canada',u'SSHRC',u'Conseil de recherches en sciences humaines du Canada',u'CRSH',u'207'],
    'Société des ponts fédéraux'                                                                                                                                     : [u'Federal Bridge Corporation',u'FBCL',u'Société des ponts fédéraux',u'SPFL',u'254'],
    'Société immobilière du Canada Limitée'                                                                                                                          : [u'Canada Lands Company Limited',u'',u'Société immobilière du Canada Limitée',u'',u'82'],
    'Standards Council of Canada'                                                                                                                                    : [u'Standards Council of Canada',u'SCC-CCN',u'Conseil canadien des normes',u'SCC-CCN',u'107'],
    'Statistics Canada'                                                                                                                                              : [u'Statistics Canada',u'StatCan',u'Statistique Canada',u'StatCan',u'256'],
    'Statistique Canada'                                                                                                                                             : [u'Statistics Canada',u'StatCan',u'Statistique Canada',u'StatCan',u'256'],
    'Status of Women Canada'                                                                                                                                         : [u'Status of Women Canada',u'SWC',u'Condition féminine Canada',u'CFC',u'147'],
    'Sécurité publique Canada'                                                                                                                                       : [u'Public Safety Canada',u'PS',u'Sécurité publique Canada',u'SP',u'214'],
    'The Correctional Investigator Canada'                                                                                                                           : [u'The Correctional Investigator Canada',u'OCI',u'L\'Enquêteur correctionnel Canada',u'BEC',u'5555'],
    'The National Battlefields Commission'                                                                                                                           : [u'The National Battlefields Commission',u'NBC',u'Commission des champs de bataille nationaux',u'CCBN',u'262'],
    'Transport Canada'                                                                                                                                               : [u'Transport Canada',u'TC',u'Transports Canada',u'TC',u'217'],
    'Transportation Appeal Tribunal of Canada'                                                                                                                       : [u'Transportation Appeal Tribunal of Canada',u'TATC',u'Tribunal d\'appel des transports du Canada',u'TATC',u'96'],
    'Transportation Safety Board of Canada'                                                                                                                          : [u'Transportation Safety Board of Canada',u'TSB',u'Bureau de la sécurité des transports du Canada',u'BST',u'215'],
    'Transports Canada'                                                                                                                                              : [u'Transport Canada',u'TC',u'Transports Canada',u'TC',u'217'],
    'Treasury Board of Canada Secretariat'                                                                                                                           : [u'Treasury Board of Canada Secretariat',u'TBS',u'Secrétariat du Conseil du Trésor du Canada',u'SCT',u'139'],
    'Treasury Board'                                                                                                                                                 : [u'Treasury Board',u'TB',u'Conseil du Trésor',u'CT',u'105'],
    'Tribunal canadien du commerce extérieur'                                                                                                                        : [u'Canadian International Trade Tribunal',u'CITT',u'Tribunal canadien du commerce extérieur',u'TCCE',u'175'],
    'Tribunal de la dotation de la fonction publique'                                                                                                                : [u'Public Service Staffing Tribunal',u'PSST',u'Tribunal de la dotation de la fonction publique',u'TDFP',u'266'],
    'Tribunal de la protection des fonctionnaires divulgateurs Canada'                                                                                               : [u'Public Servants Disclosure Protection Tribunal Canada',u'PSDPTC',u'Tribunal de la protection des fonctionnaires divulgateurs Canada',u'TPFDC',u'40'],
    'Tribunal des anciens combattants (révision et appel)'                                                                                                           : [u'Veterans Review and Appeal Board',u'VRAB',u'Tribunal des anciens combattants (révision et appel)',u'TACRA',u'85'],
    'Tribunal des droits de la personne du Canada'                                                                                                                   : [u'Human Rights Tribunal of Canada',u'HRTC',u'Tribunal des droits de la personne du Canada',u'TDPC',u'164'],
    'Veterans Affairs Canada'                                                                                                                                        : [u'Veterans Affairs Canada',u'VAC',u'Anciens Combattants Canada',u'ACC',u'189'],
    'Veterans Review and Appeal Board'                                                                                                                               : [u'Veterans Review and Appeal Board',u'VRAB',u'Tribunal des anciens combattants (révision et appel)',u'TACRA',u'85'],
    'VIA Rail Canada Inc.'                                                                                                                                           : [u'VIA Rail Canada Inc.',u'',u'VIA Rail Canada Inc.',u'',u'55555'],
    'VIA Rail Canada Inc.'                                                                                                                                           : [u'VIA Rail Canada Inc.',u'',u'VIA Rail Canada Inc.',u'',u'55555'],
    'Western Economic Diversification Canada'                                                                                                                        : [u'Western Economic Diversification Canada',u'WD',u'Diversification de l\'économie de l\'Ouest Canada',u'DEO',u'55'],
    'Windsor-Detroit Bridge Authority'                                                                                                                               : [u'Windsor-Detroit Bridge Authority',u'',u'Autorité du pont Windsor-Détroit',u'',u'55553'],
    'École de la fonction publique du Canada'                                                                                                                        : [u'Canada School of Public Service',u'CSPS',u'École de la fonction publique du Canada',u'EFPC',u'73'],
    'Élections Canada'                                                                                                                                              : [u'Elections Canada',u'elections',u'Élections Canada',u'elections',u'285']
}

ResourceType = {
    'abstract'                               :[u'abstract'],
    'sommaire'                               :[u'abstract'],
    'agreement'                              :[u'agreement'],
    'entente'                                :[u'agreement'],
    'contractual material'                   :[u'contractual_material'],
    'contenu contractuel'                    :[u'contractual_material'],
    'intergovernmental agreement'            :[u'intergovernmental_agreement'],
    'entente intergouvernementale'           :[u'intergovernmental_agreement'],
    'lease'                                  :[u'lease'],
    'bail'                                   :[u'lease'],
    'memorandum of understanding'            :[u'memorandum_of_understanding'],
    'protocole d’entente'                    :[u'memorandum_of_understanding'],
    'nondisclosure agreement'                :[u'nondisclosure_agreement'],
    'accord de non divulgation'              :[u'nondisclosure_agreement'],
    'service-level agreement'                :[u'service-level_agreement'],
    'entente de niveau de service'           :[u'service-level_agreement'],
    'affidavit'                              :[u'affidavit'],
    'application'                            :[u'application'],
    'demande'                                :[u'application'],
    'api'                                    :[u'api'],
    'architectural or technical design'      :[u'architectural_or_technical_design'],
    'conception architecturale ou technique' :[u'architectural_or_technical_design'],
    'article'                                :[u'article'],
    'assessment'                             :[u'assessment'],
    'évaluation'                             :[u'assessment'],
    'audit'                                  :[u'audit'],
    'environmental assessment'               :[u'environmental_assessment'],
    'évaluation environnementale'            :[u'environmental_assessment'],
    'examination'                            :[u'examination'],
    'examen'                                 :[u'examination'],
    'gap assessment'                         :[u'gap_assessment'],
    'évaluation des écarts'                  :[u'gap_assessment'],
    'lessons learned'                        :[u'lessons_learned'],
    'leçons apprises'                        :[u'lessons_learned'],
    'performance indicator'                  :[u'performance_indicator'],
    'indicateur de rendement'                :[u'performance_indicator'],
    'risk assessment'                        :[u'risk_assessment'],
    'évaluation des risques'                 :[u'risk_assessment'],
    'biography'                              :[u'biography'],
    'biographie'                             :[u'biography'],
    'briefing material'                      :[u'briefing_material'],
    'matériel de breffage'                   :[u'briefing_material'],
    'backgrounder'                           :[u'backgrounder'],
    'précis d’information'                   :[u'backgrounder'],
    'business case'                          :[u'business_case'],
    'analyse de rentabilisation'             :[u'business_case'],
    'claim'                                  :[u'claim'],
    'réclamation'                            :[u'claim'],
    'comments'                               :[u'comments'],
    'commentaires'                           :[u'comments'],
    'conference proceedings'                 :[u'conference_proceedings'],
    'actes de la conférence'                 :[u'conference_proceedings'],
    'consultation'                           :[u'consultation'],
    'consultation'                           :[u'consultation'],
    'contact information'                    :[u'contact_information'],
    'coordonnées'                            :[u'contact_information'],
    'correspondence'                         :[u'correspondence'],
    'correspondance'                         :[u'correspondence'],
    'ministerial correspondence'             :[u'ministerial_correspondence'],
    'correspondance ministérielle'           :[u'ministerial_correspondence'],
    'memorandum'                             :[u'memorandum'],
    'note de service'                        :[u'memorandum'],
    'dataset'                                :[u'dataset'],
    'jeu de données'                         :[u'dataset'],
    'delegation of authority'                :[u'delegation_of_authority'],
    'délégation des pouvoirs'                :[u'delegation_of_authority'],
    'educational material'                   :[u'educational_material'],
    'matériel pédagogique'                   :[u'educational_material'],
    'employment opportunity'                 :[u'employment_opportunity'],
    'possibilité d’emploi'                   :[u'employment_opportunity'],
    'event'                                  :[u'event'],
    'événement'                              :[u'event'],
    'fact sheet'                             :[u'fact_sheet'],
    'feuille de renseignements'              :[u'fact_sheet'],
    'financial material'                     :[u'financial_material'],
    'document financier'                     :[u'financial_material'],
    'budget'                                 :[u'budget'],
    'funding proposal'                       :[u'funding_proposal'],
    'proposition de financement'             :[u'funding_proposal'],
    'invoice'                                :[u'invoice'],
    'facture'                                :[u'invoice'],
    'financial statement'                    :[u'financial_statement'],
    'états financiers'                       :[u'financial_statement'],
    'form'                                   :[u'form'],
    'formulaire'                             :[u'form'],
    'framework'                              :[u'framework'],
    'cadre'                                  :[u'framework'],
    'geospatial material'                    :[u'geospatial_material'],
    'matériel géospatial'                    :[u'geospatial_material'],
    'guide'                                  :[u'guide'],
    'guide'                                  :[u'guide'],
    'best practices'                         :[u'best_practices'],
    'pratiques exemplaires'                  :[u'best_practices'],
    'intellectual property statement'        :[u'intellectual_property_statement'],
    'Énoncé sur la propriété intellectuelle' :[u'intellectual_property_statement'],
    'legal complaint'                        :[u'legal_complaint'],
    'plainte légale'                         :[u'legal_complaint'],
    'legal opinion'                          :[u'legal_opinion'],
    'avis juridique'                         :[u'legal_opinion'],
    'legislation and regulations'            :[u'legislation_and_regulations'],
    'lois et règlements'                     :[u'legislation_and_regulations'],
    'licenses and permits'                   :[u'licenses_and_permits'],
    'licences et permis'                     :[u'licenses_and_permits'],
    'literary material'                      :[u'literary_material'],
    'ouvrages littéraires'                   :[u'literary_material'],
    'media release'                          :[u'media_release'],
    'communiqué de presse'                   :[u'media_release'],
    'statement'                              :[u'statement'],
    'énoncé'                                 :[u'statement'],
    'meeting material'                       :[u'meeting_material'],
    'documentation de la réunion'            :[u'meeting_material'],
    'agenda'                                 :[u'agenda'],
    'programme'                              :[u'agenda'],
    'minutes'                                :[u'minutes'],
    'procès-verbaux'                         :[u'minutes'],
    'memorandum to Cabinet'                  :[u'memorandum_to_cabinet'],
    'mémoire au Cabinet'                     :[u'memorandum_to_cabinet'],
    'multimedia resource'                    :[u'multimedia_resource'],
    'ressource multimédia'                   :[u'multimedia_resource'],
    'notice'                                 :[u'notice'],
    'avis'                                   :[u'notice'],
    'organizational description'             :[u'organizational_description'],
    'description organisationnelle'          :[u'organizational_description'],
    'plan'                                   :[u'plan'],
    'business plan'                          :[u'business_plan'],
    'plan d’activités'                       :[u'business_plan'],
    'strategic plan'                         :[u'strategic_plan'],
    'plan stratégique'                       :[u'strategic_plan'],
    'policy'                                 :[u'policy'],
    'politique'                              :[u'policy'],
    'white paper'                            :[u'white_paper'],
    'livre blanc'                            :[u'white_paper'],
    'presentation'                           :[u'presentation'],
    'présentation'                           :[u'presentation'],
    'procedure'                              :[u'procedure'],
    'procédure'                              :[u'procedure'],
    'profile'                                :[u'profile'],
    'profil'                                 :[u'profile'],
    'project material'                       :[u'project_material'],
    'documents du projet'                    :[u'project_material'],
    'project charter'                        :[u'project_charter'],
    'charte de projet'                       :[u'project_charter'],
    'project plan'                           :[u'project_plan'],
    'plan du projet'                         :[u'project_plan'],
    'project proposal'                       :[u'project_proposal'],
    'proposition de projet'                  :[u'project_proposal'],
    'promotional material'                   :[u'promotional_material'],
    'documents promotionnels'                :[u'promotional_material'],
    'publication'                            :[u'publication'],
    'Q & A'                                  :[u'faq'],
    'FAQ'                                    :[u'faq'],
    'Q et R'                                 :[u'faq'],
    'foire aux questions'                    :[u'faq'],
    'record of decision'                     :[u'record_of_decision'],
    'compte rendu des décisions'             :[u'record_of_decision'],
    'report'                                 :[u'report'],
    'rapport'                                :[u'report'],
    'annual report'                          :[u'annual_report'],
    'rapport annuel'                         :[u'annual_report'],
    'interim report'                         :[u'interim_report'],
    'rapport d’étape'                        :[u'interim_report'],
    'research proposal'                      :[u'research_proposal'],
    'projet de recherche'                    :[u'research_proposal'],
    'resource list'                          :[u'resource_list'],
    'liste de référence'                     :[u'resource_list'],
    'routing slip'                           :[u'routing_slip'],
    'bordereau d’acheminement'               :[u'routing_slip'],
    'Social media resource'                  :[u'blog_entry'],
    'blog entry'                             :[u'blog_entry'],
    'ressources des médias sociaux'          :[u'blog_entry'],
    'entrée de blogue'                       :[u'blog_entry'],
    'sound recording'                        :[u'sound_recording'],
    'enregistrement sonore'                  :[u'sound_recording'],
    'specification'                          :[u'specification'],
    'spécification'                          :[u'specification'],
    'statistics'                             :[u'statistics'],
    'statistiques'                           :[u'statistics'],
    'still image'                            :[u'still_image'],
    'image fixe'                             :[u'still_image'],
    'submission'                             :[u'submission'],
    'présentation'                           :[u'submission'],
    'survey'                                 :[u'survey'],
    'sondage'                                :[u'survey'],
    'terminology'                            :[u'terminology'],
    'terminologie'                           :[u'terminology'],
    'terms of reference'                     :[u'terms_of_reference'],
    'mandat'                                 :[u'terms_of_reference'],
    'tool'                                   :[u'tool'],
    'outil'                                  :[u'tool'],
    'training material'                      :[u'training_material'],
    'matériel didactique'                    :[u'training_material'],
    'transcript'                             :[u'transcript'],
    'transcription'                          :[u'transcript'],
    'web service'                            :[u'web_service'],
    'service web'                            :[u'web_service'],
    'website'                                :[u'website'],
    'site Web'                               :[u'website'],
    'workflow'                               :[u'workflow'],
    'flux des travaux'                       :[u'workflow'],
    
    'abstract'                               :[u'abstract'],
    'affidavit'                              :[u'affidavit'],
    'agenda'                                 :[u'agenda'],
    'agreement'                              :[u'agreement'],
    'annual_report'                          :[u'annual_report'],
    'api'                                    :[u'api'],
    'application'                            :[u'application'],
    'architectural_or_technical_design'      :[u'architectural_or_technical_design'],
    'article'                                :[u'article'],
    'assessment'                             :[u'assessment'],
    'audit'                                  :[u'audit'],
    'backgrounder'                           :[u'backgrounder'],
    'best_practices'                         :[u'best_practices'],
    'biography'                              :[u'biography'],
    'blog_entry'                             :[u'blog_entry'],
    'briefing_material'                      :[u'briefing_material'],
    'budget'                                 :[u'budget'],
    'business_case'                          :[u'business_case'],
    'business_plan'                          :[u'business_plan'],
    'claim'                                  :[u'claim'],
    'comments'                               :[u'comments'],
    'conference_proceedings'                 :[u'conference_proceedings'],
    'consultation'                           :[u'consultation'],
    'contact_information'                    :[u'contact_information'],
    'contractual_material'                   :[u'contractual_material'],
    'correspondence'                         :[u'correspondence'],
    'dataset'                                :[u'dataset'],
    'delegation_of_authority'                :[u'delegation_of_authority'],
    'educational_material'                   :[u'educational_material'],
    'employment_opportunity'                 :[u'employment_opportunity'],
    'environmental_assessment'               :[u'environmental_assessment'],
    'event'                                  :[u'event'],
    'examination'                            :[u'examination'],
    'fact_sheet'                             :[u'fact_sheet'],
    'faq'                                    :[u'faq'],
    'financial_material'                     :[u'financial_material'],
    'financial_statement'                    :[u'financial_statement'],
    'form'                                   :[u'form'],
    'framework'                              :[u'framework'],
    'funding_proposal'                       :[u'funding_proposal'],
    'gap_assessment'                         :[u'gap_assessment'],
    'geospatial_material'                    :[u'geospatial_material'],
    'guide'                                  :[u'guide'],
    'intellectual_property_statement'        :[u'intellectual_property_statement'],
    'intergovernmental_agreement'            :[u'intergovernmental_agreement'],
    'interim_report'                         :[u'interim_report'],
    'invoice'                                :[u'invoice'],
    'lease'                                  :[u'lease'],
    'legal_complaint'                        :[u'legal_complaint'],
    'legal_opinion'                          :[u'legal_opinion'],
    'legislation_and_regulations'            :[u'legislation_and_regulations'],
    'lessons_learned'                        :[u'lessons_learned'],
    'licenses_and_permits'                   :[u'licenses_and_permits'],
    'literary_material'                      :[u'literary_material'],
    'media_release'                          :[u'media_release'],
    'meeting_material'                       :[u'meeting_material'],
    'memorandum'                             :[u'memorandum'],
    'memorandum_of_understanding'            :[u'memorandum_of_understanding'],
    'memorandum_to_cabinet'                  :[u'memorandum_to_cabinet'],
    'ministerial_correspondence'             :[u'ministerial_correspondence'],
    'minutes'                                :[u'minutes'],
    'multimedia_resource'                    :[u'multimedia_resource'],
    'nondisclosure_agreement'                :[u'nondisclosure_agreement'],
    'notice'                                 :[u'notice'],
    'organizational_description'             :[u'organizational_description'],
    'performance_indicator'                  :[u'performance_indicator'],
    'plan'                                   :[u'plan'],
    'policy'                                 :[u'policy'],
    'presentation'                           :[u'presentation'],
    'procedure'                              :[u'procedure'],
    'profile'                                :[u'profile'],
    'project_charter'                        :[u'project_charter'],
    'project_material'                       :[u'project_material'],
    'project_plan'                           :[u'project_plan'],
    'project_proposal'                       :[u'project_proposal'],
    'promotional_material'                   :[u'promotional_material'],
    'publication'                            :[u'publication'],
    'record_of_decision'                     :[u'record_of_decision'],
    'report'                                 :[u'report'],
    'research_proposal'                      :[u'research_proposal'],
    'resource_list'                          :[u'resource_list'],
    'risk_assessment'                        :[u'risk_assessment'],
    'routing_slip'                           :[u'routing_slip'],
    'service-level_agreement'                :[u'service-level_agreement'],
    'sound_recording'                        :[u'sound_recording'],
    'specification'                          :[u'specification'],
    'statement'                              :[u'statement'],
    'statistics'                             :[u'statistics'],
    'still_image'                            :[u'still_image'],
    'strategic_plan'                         :[u'strategic_plan'],
    'submission'                             :[u'submission'],
    'survey'                                 :[u'survey'],
    'terminology'                            :[u'terminology'],
    'terms_of_reference'                     :[u'terms_of_reference'],
    'tool'                                   :[u'tool'],
    'training_material'                      :[u'training_material'],
    'transcript'                             :[u'transcript'],
    'web_service'                            :[u'web_service'],
    'website'                                :[u'website'],
    'white_paper'                            :[u'white_paper'],
    'workflow'                               :[u'workflow'],

}


#old_ResourceType = [
#    'abstract',
#    'affidavit',
#    'agenda',
#    'agreement',
#    'annual_report',
#    'application',
#    'architectural_or_technical_design',
#    'article',
#    'assessment',
#    'audit',
#    'backgrounder',
#    'best_practices',
#    'biography',
#    'blog_entry',
#    'briefing_material',
#    'budget',
#    'business_case',
#    'business_plan',
#    'claim',
#    'comments',
#    'conference_proceedings',
#    'consultation',
#    'contact_information',
#    'contractual_material',
#    'correspondence',
#    'dataset',
#    'delegation_of_authority',
#    'educational_material',
#    'employment_opportunity',
#    'environmental_assessment',
#    'event',
#    'examination',
#    'fact_sheet',
#    'faq',
#    'financial_material',
#    'financial_statement',
#    'form',
#    'framework',
#    'funding_proposal',
#    'gap_assessment',
#    'geospatial_material',
#    'guide',
#    'intellectual_property_statement',
#    'intergovernmental_agreement',
#    'interim_report',
#    'invoice',
#    'lease',
#    'legal_complaint',
#    'legal_opinion',
#    'legislation_and_regulations',
#    'lessons_learned',
#    'licenses_and_permits',
#    'literary_material',
#    'media_release',
#    'meeting_material',
#    'memorandum',
#    'memorandum_of_understanding',
#    'memorandum_to_cabinet',
#    'ministerial_correspondence',
#    'minutes',
#    'multimedia_resource',
#    'nondisclosure_agreement',
#    'notice',
#    'organizational_description',
#    'performance_indicator',
#    'plan',
#    'policy',
#    'presentation',
#    'procedure',
#    'profile',
#    'project_charter',
#    'project_material',
#    'project_plan',
#    'project_proposal',
#    'promotional_material',
#    'publication',
#    'record_of_decision',
#    'report',
#    'research_proposal',
#    'resource_list',
#    'risk_assessment',
#    'routing_slip',
#    'service-level_agreement',
#    'sound_recording',
#    'specification',
#    'statement',
#    'statistics',
#    'still_image',
#    'strategic_plan',
#    'submission',
#    'survey',
#    'terminology',
#    'terms_of_reference',
#    'tool',
#    'training_material',
#    'transcript',
#    'website',
#    'white_paper',
#    'workflow',
#    'web_service'
#]

CL_Formats = [
    'AAC',
    'AIFF',
    'APK',
    'ASCII Grid',
    'AVI',
    'BMP',
    'BWF',
    'CCT',
    'CDED ASCII',
    'CDR',
    'COD',
    'CSV',
    'DBD',
    'DBF',
    'DICOM',
    'DNG',
    'DOC',
    'DOCX',
    'DXF',
    'E00',
    'ECW',
    'EDI',
    'EMF',
    'EPUB3',
    'EPUB2',
    'EPS',
    'ESRI REST',
    'EXE',
    'FGDB/GDB',
    'Flat raster binary',
    'GeoPDF',
    'GeoRSS',
    'GeoTIF',
    'GEOJSON',
    'GPKG',
    'GIF',
    'GML',
    'GRIB1',
    'GRIB2',
    'HDF',
    'HTML',
    'IATI',
    'IPA',
    'JFIF',
    'JP2',
    'JPG',
    'JSON',
    'JSONL',
    'KML',
    'KMZ',
    'LAS',
    'LYR',
    'MFX',
    'MOV',
    'MPEG',
    'MPEG-1',
    'MP3',
    'MXD',
    'NetCDF',
    'NT',
    'ODP',
    'ODS',
    'ODT',
    'other',
    'PDF',
    'PDF/A-1',
    'PDF/A-2',
    'PNG',
    'PPT',
    'RDF',
    'RDFa',
    'RSS',
    'RTF',
    'SAR',
    'SAV',
    'SEGY',
    'SHP',
    'SQL',
    'SQLITE3',
    'SQLITE',
    'SVG',
    'TAB',
    'TFW',
    'TIFF',
    'TRIG',
    'TRIX',
    'TTL',
    'TXT',
    'VPF',
    'WAV',
    'WCS',
    'WFS',
    'WMS',
    'WMTS',
    'WMV',
    'XML',
    'XLS',
    'XLSM',
    'ZIP'
]

CL_Subjects = {
    'farming': [
        'Farming',
        'Agriculture',
        'Agriculture',
        'agriculture'],
    'biota': [
        'Biota',
        'Biote',
        'Nature and Environment, Science and Technology',
        'nature_and_environment,science_and_technology'],
    'boundaries': [
        'Boundaries',
        'Frontières',
        'Government and Politics',
        'government_and_politics'],
    'climatologyMeteorologyAtmosphere': [
        'Climatology / Meteorology / Atmosphere',
        'Climatologie / Météorologie / Atmosphère',
        'Nature and Environment, Science and Technology',
        'nature_and_environment,science_and_technology'],
    'economy': [
        'Economy',
        'Économie',
        'Economics and Industry',
        'economics_and_industry'],
    'elevation': [
        'Elevation',
        'Élévation',
        'Form Descriptors',
        'form_descriptors'],
    'environment': [
        'Environment',
        'Environnement',
        'Nature and Environment',
        'nature_and_environment'],
    'geoscientificInformation': [
        'Geoscientific Information',
        'Information géoscientifique',
        'Nature and Environment, Science and Technology, Form Descriptors',
        'nature_and_environment,science_and_technology,form_descriptors'],
    'health': [
        'Health',
        'Santé',
        'Health and Safety',
        'health_and_safety'],
    'imageryBaseMapsEarthCover': [
        'Imagery Base Maps Earth Cover',
        'Imagerie carte de base couverture terrestre',
        'Form Descriptors',
        'form_descriptors'],
    'intelligenceMilitary': [
        'Intelligence Military',
        'Renseignements militaires',
        'Military',
        'military'],
    'inlandWaters': [
        'Inland Waters',
        'Eaux intérieures',
        'Nature and Environment',
        'nature_and_environment'],
    'location': [
        'Location',
        'Localisation',
        'Form Descriptors',
        'form_descriptors'],
    'oceans': [
        'Oceans',
        'Océans',
        'Nature and Environment',
        'nature_and_environment'],
    'planningCadastre': [
        'Planning Cadastre',
        'Aménagement cadastre',
        'Nature and Environment, Form Descriptors, Economics and Industry',
        'nature_and_environment,form_descriptors,economics_and_industry'],
    'society': [
        'Society',
        'Société',
        'Society and Culture',
        'society_and_culture'],
    'structure': [
        'Structure',
        'Structures',
        'Economics and Industry',
        'economics_and_industry'],
    'transportation': [
        'Transportation',
        'Transport',
        'Transport',
        'transport'],
    'utilitiesCommunication': [
        'Utilities Communication',
        'Services communication',
        'Economics and Industry, Information and Communications',
        'economics_and_industry,information_and_communications']
}


OGP_catalogueType = {
    'Data'       : [u'Data',                       u'Données'],
    'Geo Data'   : [u'Geo Data',                   u'Géo'],
    'FGP Data'   : [u'FGP Data',                   u'FGP Data'],
    'Données'    : [u'Data',                       u'Données'],
    'Géo'        : [u'Geo Data',                   u'Géo'],
    'FGP Data'   : [u'FGP Data',                   u'FGP Data']
}

if __name__ == "__main__":
    arguments = docopt.docopt(__doc__)
    sys.exit(main())
    