#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Updates schema validation lists
# Requires PyYaml. Install using: $ pip install pyyaml

import yaml
import urllib, json

url = "https://raw.githubusercontent.com/open-data/ckanext-canada/master/ckanext/canada/schemas/presets.yaml"
response = urllib.urlopen(url)

data = yaml.safe_load(response.read())

# ----------------------------------------
# Generate CL_Formats.py
# ----------------------------------------

k = 0
for node in data['presets']:

    if node['preset_name'] == "canada_resource_format":
        break
    k += 1

formats = []
canada_resource_formats = data['presets'][k]

for f in canada_resource_formats['values']['choices']:
    formats.append("'%s'" % f['value'])

formats.sort()

wr = open('CL_Formats.py', 'w')
wr.write('# -*- coding: utf-8 -*-\n\nCL_Formats = [\n    ' + ',\n    '.join(formats) + '\n]')

# ----------------------------------------
# Generate ResourceType.py
# ----------------------------------------

k = 0
for node in data['presets']:

    if node['preset_name'] == "canada_resource_type":
        break
    k += 1

types = []
canada_resource_type = data['presets'][k]

for t in canada_resource_type['values']['choices']:
    label_en = t['label']['en'].lower().encode('utf8', 'replace')
    label_fr = t['label']['fr'].lower().encode('utf8', 'replace')

    types.append("'%s'" % label_en + ":[u'%s']" % t['value'].lower())
    types.append("'%s'" % label_fr + ":[u'%s']" % t['value'].lower())

wr = open('ResourceType.py', 'w')
wr.write('# -*- coding: utf-8 -*-\n\nResourceType = {\n    ' + ',\n    '.join(types) + '\n}')