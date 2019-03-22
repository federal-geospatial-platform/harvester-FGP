#!/usr/bin/env python
# -*- coding: utf-8 -*-

# https://github.com/ckan/ckanapi
# https://open.canada.ca/data/en/api/3/action/package_search?fq=collection:fgp&start=0&rows=1

import requests
import sys
import xml.etree.ElementTree as ET

from ckanapi import RemoteCKAN

def checkFGP(uuid):

    r = requests.get('https://csw.open.canada.ca/geonetwork/srv/csw?service=CSW&version=2.0.2&request=GetRecordById&id=%s&elementsetname=brief' % uuid)

    root = ET.fromstring(r.text.encode('utf-8'))

    namespaces = {'csw': 'http://www.opengis.net/cat/csw/2.0.2'}

    if not root.findall('csw:BriefRecord', namespaces):
        print uuid + ' [Orphaned]'

i = 0
ogp_ids = []
ogp = RemoteCKAN('https://open.canada.ca/data')
search = ogp.call_action('package_search', {'fq':'collection:fgp', 'start': i})

print '\nSearching for UUId\'s\n'
while(True):
    
    if search['results']:
        sys.stdout.write('.')
        sys.stdout.flush()
        for record in search['results']:
            ogp_ids.append(record['id'])
            i +=1
            
    else:
        break

    search = ogp.call_action('package_search', {'fq':'collection:fgp', 'start': i})

print '\n\n' + str(len(ogp_ids)) + ' UUID\'s found!\n'
print 'Looking for orphans...\n'

for id in ogp_ids:
    checkFGP(id)

