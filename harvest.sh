
#!/bin/bash

# Lockfile
# 86400 — one day
# 10800 - three hours

# Jump into the Open Maps harvester directory
# cd /home/odatsrv/_harvester_OpenMaps

if [ -e "run.lock" ]; then
    if [ "$(( $(date +"%s") - $(stat -c "%Y" run.lock) ))" -lt "10800" ]; then
        echo "Aborting: Lock file 'run.lock' found"
        exit 0
    fi
fi

date +"%Y-%m-%dT%H:%M:%SZ" > run.lock

# Need to enable python27
# /usr/bin/scl enable python27

# Jump into the Open Maps harvester directory
# cd /home/odatsrv/_harvester_OpenMaps

# Last run info
if [ ! -e "run.last" ]; then
    echo "1970-01-01T00:00:01Z" > run.last
fi
OGS_HARVEST_LAST_RUN=$(cat run.last)
# /bin/date --date "2 minutes ago" +"%Y-%m-%dT%H:%M:%SZ" > run.last

# Now updating run.last after successful CKAN load
# date +"%Y-%m-%dT%H:%M:%SZ" > run.last

echo "Run starting from:"
echo $OGS_HARVEST_LAST_RUN

# AND THEN the virtual environment
# . /var/www/html/venv/staging-portal/bin/activate

# Collect the latest data
# /home/odatsrv/_harvester_OpenMaps/harvest_hnap.py -f $OGS_HARVEST_LAST_RUN > harvested_records.xml
./harvest_hnap.py -f $OGS_HARVEST_LAST_RUN > harvested_records.xml & pid=$!

# Show progress as this can take several minutes
spin='-\|/'
i=0
while kill -0 $pid 2>/dev/null
do
  i=$(( (i+1) %4 ))
  printf "\r${spin:$i:1}"
  sleep .1
done
printf "\r"

# Create the common core JSON file
/bin/cat harvested_records.xml | ./hnap2cc-json.py

# Convert csv errors to html
./csv2html.py -f harvested_record_errors.csv

# myfilesize=`stat -c %s harvested_records.jl` # for Linux
myfilesize=`stat -f %z harvested_records.jl` # for OSX

if [ $myfilesize = 0 ]; then
    echo "No new/updated records since last harvest, skipping load into CKAN"
else
    echo "Found new/updated records, loading into CKAN..."
    # cd /var/www/html/open_gov/staging-portal/ckan
    # ckanapi load datasets -I ~/_harvester_OpenMaps/harvested_records.jl -c production.ini

    # STAGING
    # ckanapi load datasets -I harvested_records.jl -r https://staging.open.canada.ca/data -a CKAN_API_KEY && date +"%Y-%m-%dT%H:%M:%SZ" > run.last

    # PRODUCTION
    # ckanapi load datasets -I harvested_records.jl -r https://open.canada.ca/data -a CKAN_API_KEY && date +"%Y-%m-%dT%H:%M:%SZ" > run.last

    # LOCAL TESTING
    # to test: ckanapi load datasets -I test_upload.jl -r https://staging.open.canada.ca/data -a CKAN_API_KEY
fi

rm run.lock