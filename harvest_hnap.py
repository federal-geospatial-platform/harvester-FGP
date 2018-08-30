#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Usage: harvest.py [-f from_iso_date_time (e.g. 1970-01-01T00:00:00Z)]

Extract HNAP XML from FGP platform

Options:
    -f ISO datetime object that defines when to start harvesting
"""

# CSW metadata extraction
# Output of this script is parsed by another into OGDMES-CKAN JSON.

# CMAJ: Shamlessly pillaged Ross Thompson's test script
# CMAJ: EC's (Mark Shaw, D. Sampson) XML Filters
# CMAJ: Tom Kralidis attempted to modernise our use of OWSLib
# CMAJ: Assembled by Chris Majewski @ StatCan

# CSW issues go to        : fgp-pgf@nrcan-rncan.gc.ca
# Metadata issues go to   : fgp-pgf@nrcan-rncan.gc.ca
# Open Data issues got to : open-ouvert@tbs-sct.gc.ca

# Called by OWSlib but may be requried if if a proxy is required
# No harm calling it early
import urllib2
# Requirement - OWSLib
# This script was writen to use OD's for of OWSLib
# > git clone https://github.com/open-data/OWSLib
# > cd /location/you/cloned/into
# > sudo python setup.py install
from owslib.csw import CatalogueServiceWeb
# Importing from a harvester.ini file
import os.path
# Pagination changes
import sys
import re
from lxml import etree
import docopt


def main():
    # Connection variables
    csw_url = 'csw.open.canada.ca/geonetwork/srv/csw'
    csw_user = None
    csw_passwd = None

    proxy_protocol = None
    proxy_url = None
    proxy_user = None
    proxy_passwd = None
    records_per_request = 10

    # Or read from a .ini file
    harvester_file = 'config/harvester.ini'
    if os.path.isfile(harvester_file):
        from ConfigParser import ConfigParser

        ini_config = ConfigParser()

        ini_config.read(harvester_file)

        csw_url = ini_config.get(
            'csw', 'url')

        # Get configuration options
        if ini_config.has_option('csw', 'username'):
            csw_user = ini_config.get(
                'csw', 'username')

            csw_passwd = ini_config.get(
                'csw', 'password')

        if ini_config.has_option('proxy', 'protocol'):
            proxy_protocol = ini_config.get(
                'proxy', 'protocol')

        if ini_config.has_option('proxy', 'url'):
            proxy_url = ini_config.get(
                'proxy', 'url')

        if ini_config.has_option('proxy', 'username'):
            proxy_user = ini_config.get(
                'proxy', 'username')
            proxy_passwd = ini_config.get(
                'proxy', 'password')

        if ini_config.has_option('processing', 'records_per_request'):
            records_per_request = int(ini_config.get(
                'processing', 'records_per_request'))

        if ini_config.has_option('processing', 'start_date'):
            start_date = ini_config.get('processing', 'start_date')

    # If your supplying a proxy
    if proxy_url:
        # And your using authentication
        if proxy_user and proxy_passwd:
            password_mgr = urllib2.HTTPPasswordMgrWithDefaultRealm()
            password_mgr.add_password(
                None, proxy_url, proxy_user, proxy_passwd)
            proxy_auth_handler = urllib2.ProxyBasicAuthHandler(password_mgr)
        # or even if your not
        else:
            proxy_auth_handler = urllib2.ProxyHandler(
                {proxy_protocol: proxy_url})

        opener = urllib2.build_opener(proxy_auth_handler)
        urllib2.install_opener(opener)

    # Fetch the data
    # csw = CatalogueServiceWeb(
    #   'https://csw_user:csw_pass@csw_url/geonetwork/srv/csw')
    if csw_user and csw_passwd:
        csw = CatalogueServiceWeb(
            'https://'+csw_url,
            username=csw_user,
            password=csw_passwd,
            timeout=20)
    else:
        csw = CatalogueServiceWeb('https://'+csw_url, timeout=20)

    request_template = """<?xml version="1.0"?>
<csw:GetRecords
    xmlns:csw="http://www.opengis.net/cat/csw/2.0.2"
    service="CSW"
    version="2.0.2"
    resultType="results"
    outputSchema="csw:IsoRecord"
    maxRecords="%d"
    startPosition="%d"
>
    <csw:Query
        typeNames="gmd:MD_Metadata">
        <csw:ElementSetName>full</csw:ElementSetName>
        <csw:Constraint
            version="1.1.0">
            <Filter
                xmlns="http://www.opengis.net/ogc"
                xmlns:gml="http://www.opengis.net/gml">
                <PropertyIsGreaterThanOrEqualTo>
                    <PropertyName>Modified</PropertyName>
                    <Literal>%s</Literal>
                </PropertyIsGreaterThanOrEqualTo>
            </Filter>
        </csw:Constraint>
    </csw:Query>
</csw:GetRecords>
"""

    # Is there a specified start date
    if arguments['-f']:
        start_date = arguments['-f']

    active_page = 0
    next_record = 1
    request_another = True

    while request_another:

        request_another = False

        # Filter records into latest updates
        #
        # Sorry Tom K., we'll be more modern ASAWC.
        # For now it's good ol' Kitchen Sink
        #
        # from owslib.fes import PropertyIsGreaterThanOrEqualTo
        # modified = PropertyIsGreaterThanOrEqualTo(
        #   'apiso:Modified',
        #   '2015-04-04'
        # )
        # csw.getrecords2(constraints=[modified])
        #
        # Kitchen Sink is the valid HNAP, we need HNAP for R1 to debug issues
        # This filter was supplied by EC, the CSW service technical lead
        current_request = request_template % (
            records_per_request,
            next_record,
            start_date
        )

        # (active_page*records_per_request)+1
        csw.getrecords2(format='xml', xml=current_request)
        active_page += 1

        # Identify if we need to continue this.
        records_root = ("/csw:GetRecordsResponse")

        # Read the file, should be a streamed input in the future
        root = etree.XML(csw.response)
        # Parse the root and itterate over each record
        records = fetchXMLArray(root, records_root)

        timestamp = fetchXMLAttribute(
            records[0], "csw:SearchStatus",
            "timestamp")[0]
        number_of_records_matched = int(fetchXMLAttribute(
            records[0], "csw:SearchResults",
            "numberOfRecordsMatched")[0]
        )
        number_of_records_returned = int(fetchXMLAttribute(
            records[0], "csw:SearchResults",
            "numberOfRecordsReturned")[0]
        )
        next_record = int(fetchXMLAttribute(
            records[0], "csw:SearchResults",
            "nextRecord")[0]
        )

        if next_record > number_of_records_matched or next_record == 0:
            pass
        else:
            request_another = True

        # When we move to Tom K's filter we can use results in an R2 unified
        # harvester
        # print csw.results
        # for rec in csw.records:
        #    print '* '+csw.records[rec].title
        # Till then we need to collect and dump the response from the CSW

        # No use minimizing the XML to try to create a XML Lines file as the
        # data has carriage returns.
        # parser = etree.XMLParser(remove_blank_text=True)
        # elem = etree.XML(csw.response, parser=parser)
        # print etree.tostring(elem)

        # Output the harvested page
        print csw.response


##################################################
# XML Extract functions
# fetchXMLArray(objectToXpath, xpath)
# fetchXMLAttribute(objectToXpath, xpath, attribute)


def fetchXMLArray(objectToXpath, xpath):
# Fetch an array which may be subsections
    return objectToXpath.xpath(xpath, namespaces={
        'gmd': 'http://www.isotc211.org/2005/gmd',
        'gco': 'http://www.isotc211.org/2005/gco',
        'gml': 'http://www.opengis.net/gml/3.2',
        'csw': 'http://www.opengis.net/cat/csw/2.0.2'})


def fetchXMLAttribute(objectToXpath, xpath, attribute):
# Fetch an attribute instead of a an element
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

if __name__ == "__main__":
    #options, arguments = docopt(__doc__)  # parse arguments based on docstring above
    arguments = docopt.docopt(__doc__)
    sys.exit(main())