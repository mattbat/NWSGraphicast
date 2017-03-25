import sys
import os
import urllib
import smtplib
import glob
import datetime
import time
import ConfigParser
#import gspread
import json
import ast
import filecmp
from oauth2client.service_account import ServiceAccountCredentials

from email.mime.image import MIMEImage
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

#Global Variables
VERSION = 0.2
html_images = ""
base_path = sys.path[0]

def printHelp():
	print ""
	print "NWSGraphicast, v" + str(VERSION)
	print "batchelderbot@gmail.com"
	print ""
	
	with open (base_path + "/README.md") as f:
		print f.read()

def sendEmail(nwsOffice, to, username, password):

	subject = "NWS - " + nwsOffice.upper()
	
	# Create the container (outer) email message.
	msg = MIMEMultipart()
	msg['Subject'] = subject + ": " + str(datetime.datetime.now().strftime("%I:%M%p, %Y-%m-%d"))
	me = username
  	family = to
	msg['From'] = me
	msg['To'] = family
	msg.preamble = subject
	
	NWS_Office_Website = "http://www.weather.gov/" + nwsOffice
	html = """<html><head></head><body><p><a href=""" + NWS_Office_Website + """>NWS Norman</a><br><a href="http://www.spc.noaa.gov/">SPC</a><br><br>""" + html_images + """</p></body></html>"""
	
	part1 = MIMEText(html, 'html')
	
	msg.attach(part1)
    	
	s = smtplib.SMTP('smtp.gmail.com:587')
	s.ehlo()
	s.starttls()
	s.ehlo()
	s.login(username, password)
	s.sendmail(me, family, msg.as_string())
	s.quit()


def isValid(StartTime, EndTime, FrontPage):
	epochTime = int(time.time())

	if (epochTime > int(StartTime) and epochTime < int(EndTime) and FrontPage == "true"):
		return True
	else:
		return False
			
def parseData(data):

	global html_images
	
	for image in data:
		StartTime = image['StartTime']
		EndTime = image['EndTime']
		FrontPage = image['FrontPage']
		order = image['order']
		radar = image['radar']
		title = image['title']
		description = image['description']
		SmallImage = image['SmallImage'].replace('\/', '/')
		FullImage = image['FullImage'].replace('\/', '/')
		ImageLoop = image['ImageLoop'].replace('\/', '/')
		graphicNumber = image['graphicNumber']
		
		if isValid(StartTime, EndTime, FrontPage):
			html_images += "<b>" + str(title) + "</b>"
			
			if str(description).lower() != "none":
				html_images += "<br>" + str(description) + "<br>"
			else:
				html_images += "<br>"
			
			if radar == "1":
				html_images += "<img src=" + "\"" + ImageLoop + "\"" + "><br><br>"
			else:
				html_images += "<img src=" + "\"" + FullImage + "\"" + "><br><br>"
				#html_images += "<img src=" + "\"" + SmallImage + "\"" + "><br><br>"


def main(argv):
	Force = False
	Continue = True
	
	Config = ConfigParser.ConfigParser()
	
	for opt in argv:
		if opt in ("-f", "--force"):
			Force = True
		elif opt in ("-h", "--help"):
			printHelp()
			Continue = False
		elif opt in ("-c", "--config"):
			nwsOffice = str(raw_input("Enter NWS Office abbreviation: "))
			gmailUsername = str(raw_input("Enter Gmail username: "))
			gmailPassword = str(raw_input("Enter Gmail password: "))
			emailTo = str(raw_input("Enter email to recieve notifications: "))
			
			if os.path.isfile(base_path + "/config.ini"):
				os.remove(base_path + "/config.ini")
			cfgfile = open(base_path + "/config.ini",'w')
			
			# add the settings to the structure of the file, and lets write it out...
			Config.add_section('UserConfig')
			Config.set('UserConfig','nwsOffice',nwsOffice)
			Config.set('UserConfig','gmailUsername',gmailUsername)
			Config.set('UserConfig','gmailPassword',gmailPassword)
			Config.set('UserConfig','emailTo',emailTo)
			Config.set('UserConfig','lastUpdate'," ")
			Config.write(cfgfile)
			cfgfile.close() 
			Continue = False
	
	if Continue == False:
		sys.exit()
	
	
	if os.path.isfile(base_path + "/config.ini") == False:
		print "ERROR: No config.ini"
		print "Run python main.py -c first to setup"
		sys.exit()
	
	
	#Read Config File
	Config.read(base_path + "/config.ini")
	section = "UserConfig"
	NWS_Office = Config.get(section, 'nwsOffice')
	Last_Update = Config.get(section, 'lastUpdate')
	gmailUsername = Config.get(section, 'gmailUsername')
	gmailPassword = Config.get(section, 'gmailPassword')
	emailTo = Config.get(section, 'emailTo')
	
	
	#Retrieve Google Sheet
	#scope = ['https://spreadsheets.google.com/feeds']
	#credentials = ServiceAccountCredentials.from_json_keyfile_name('NWSGraphicast-14bedb8c9d18.json', scope)
	#gc = gspread.authorize(credentials)
	

	#spreadsheet = gc.open("NWSGraphicast")
	#response_wks = spreadsheet.worksheet("Responses")

	#Determine which NWS offices to update
	#responses = response_wks.get_all_values()
	#numrows = len(responses)
	#numcols = len(responses[0])
	
	#Skip the header row and timestamp col
	#for r in range(1, numrows):
	#	for c in range(1, numcols):
	#		print responses[r][c]
	
	
	
	
	graphicast_data = base_path + "/graphicast.data"
	old_graphicast_data = graphicast_data + "_last_update"
	
	
	mesonet_address = "http://www.mesonet.org/index.php/api/nws_products/graphicast_info/"
	urllib.urlretrieve(mesonet_address + NWS_Office, graphicast_data)
	
	changed = not (filecmp.cmp(graphicast_data, old_graphicast_data))
	
	if changed or Force:
		
		with open(graphicast_data) as f:
			flist=ast.literal_eval(f.read())
		
		parseData(flist)
		
		sendEmail(NWS_Office, emailTo, gmailUsername, gmailPassword)
		os.rename (graphicast_data, old_graphicast_data)

		
		
#Start here
main(sys.argv)