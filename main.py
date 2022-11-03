import sys
import os
import urllib.request
import smtplib
import glob
import datetime
import time
import configparser
import gspread
import json
import ast
import filecmp
from oauth2client.service_account import ServiceAccountCredentials

from email.mime.image import MIMEImage
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from multiprocessing import context
import ssl

#Global Variables
VERSION = 0.4
html_images = ""
base_path = sys.path[0]
graphicastFileName = "graphicast.data"
last_update = ".last_update"

def printHelp():
	print ("")
	print ("NWSGraphicast, v" + str(VERSION))
	print ("batchelderbot@gmail.com")
	print ("")
	
	with open (base_path + "/README.md") as f:
		print (f.read())

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
	Form_Website = "https://docs.google.com/forms/d/e/1FAIpQLSfxyivtsu929py3bbjGvbVIiasN_rw1kXbz0nNA2fNLQMUCVw/viewform?usp=sf_link"
	html = """<html><head></head><body><p>""" + html_images + """<br><hr></p><p><a href=""" + NWS_Office_Website + """>""" + subject + """</a><br><a href="http://www.spc.noaa.gov/">Storm Prediction Center (SPC)</a><br><br>""" + """<a href=""" + Form_Website + """>""" + "Subscription Preferences" + """</a>""" + """</p></body></html>"""
	
	part1 = MIMEText(html, 'html')
	
	msg.attach(part1)
	
	context = ssl.create_default_context()

	with smtplib.SMTP_SSL('smtp.gmail.com', 465, context=context) as smtp:
		smtp.login(username, password)
		smtp.sendmail(username, to, msg.as_string())

def isValid(StartTime, EndTime, FrontPage):
	epochTime = int(time.time())

	if (epochTime > int(StartTime) and epochTime < int(EndTime) and FrontPage == "true"):
		return True
	else:
		return False
			
def parseData(nwsOffice, imageSize, data):

	global html_images
	html_images = ''
	
	for image in data:
		Office = image['Office']
		
		if Office == "No Image Available":
			html_images += "<b>" + "No Images Available" + "</b><br>"
		else:
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
					if imageSize == "Large":
						html_images += "<img src=" + "\"" + FullImage + "\"" + "><br><br>"
					else:
						html_images += "<img src=" + "\"" + SmallImage + "\"" + "><br><br>"


def main(argv):
	Force = False
	Continue = True
	
	Config = configparser.ConfigParser()
	
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
		print ("ERROR: No config.ini")
		print ("Run python main.py -c first to setup")
		sys.exit()
	
	
	#Read Config File
	Config.read(base_path + "/config.ini")
	section = "UserConfig"
	#NWS_Office = Config.get(section, 'nwsOffice')
	#Last_Update = Config.get(section, 'lastUpdate')
	gmailUsername = Config.get(section, 'gmailUsername')
	gmailPassword = Config.get(section, 'gmailPassword')
	#emailTo = Config.get(section, 'emailTo')
	
	
	#Retrieve Google Sheet
	scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
	credentials = ServiceAccountCredentials.from_json_keyfile_name(base_path + '/NWSGraphicast-14bedb8c9d18.json', scope)
	gc = gspread.authorize(credentials)

	spreadsheet = gc.open("NWSGraphicast")
	response_wks = spreadsheet.worksheet("Responses")

	#Determine which NWS offices to update
	responses = response_wks.get_all_values()
	numrows = len(responses)
	numcols = len(responses[0])
	
	#Skip the header row and timestamp col
	for r in range(1, numrows):
	
		emailTo = responses[r][1]
		zipcode = responses[r][2]
		emailFrequency = responses[r][3]
		Image_Size = responses[r][4]
		
		if emailFrequency != "No Emails":

			#Find NWS Office
			getNWSOfficeURL = "http://forecast.weather.gov/zipcity.php" + "?inputstring=" + zipcode
			nwsOfficeURLResponse = urllib.request.urlopen(getNWSOfficeURL).geturl().lower().split('site=')
			NWS_Office = nwsOfficeURLResponse[1][0:3]

			#Determine files
			
			graphicast_data = base_path + "/" + graphicastFileName + "." + NWS_Office
			old_graphicast_data = graphicast_data + last_update
		
			#Retrieve Graphicasts for given NWS Office
			mesonet_address = "http://www.mesonet.org/index.php/api/nws_products/graphicast_info/"
			urllib.request.urlretrieve(mesonet_address + NWS_Office, graphicast_data)
	
			#Determine if there's been an update
			if os.path.exists(old_graphicast_data):
				changed = not (filecmp.cmp(graphicast_data, old_graphicast_data))
			else:
				changed = True
	
			#Process Data
			if changed or Force:
				with open(graphicast_data) as f:
					flist=ast.literal_eval(f.read())
					parseData(NWS_Office, Image_Size, flist)
					sendEmail(NWS_Office, emailTo, gmailUsername, gmailPassword)
	
	
	#Rename files
	files = os.listdir(base_path)
	for currentFile in files:
		if graphicastFileName in currentFile:
			if last_update not in currentFile:
				os.rename (base_path + "/" + currentFile, base_path + "/" + currentFile + last_update)

		
		
#Start here
main(sys.argv)
