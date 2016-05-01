import sys
import xml.etree.ElementTree as ET
import os
import urllib
import smtplib
import glob
import datetime
import time
import ConfigParser

from email.mime.image import MIMEImage
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def printHelp():
	print "NWSGraphicast, v0.1"
	print "batchelderbot@gmail.com"

def sendEmail(subject, to, username, password):
	# Create the container (outer) email message.
	msg = MIMEMultipart()
	msg['Subject'] = subject + " " + str(datetime.datetime.now())
	me = username
  	family = to
	msg['From'] = me
	msg['To'] = family
	msg.preamble = subject
	
	html = """<html><head></head><body><p><a href="http://www.srh.noaa.gov/oun/">NWS Norman</a><br><a href="http://www.spc.noaa.gov/">SPC</a><br><br>""" + html_images + """</p></body></html>"""
	
	part1 = MIMEText(html, 'html')
	
	msg.attach(part1)

	# Assume we know that the image files are all in PNG format
	#path = "*.jpg"
	#for file in glob.glob(path):
		# Open the files in binary mode.  Let the MIMEImage class automatically
    	# guess the specific image type.
		#fp = open(file, 'rb')
		#img = MIMEImage(fp.read())
		#fp.close()
		#msg.attach(img)
    	
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
	
def parseXML(root):

	global html_images
  	
	for graphicast in root.iter('graphicast'):
		StartTime = graphicast.find('StartTime').text
		EndTime = graphicast.find('EndTime').text
		FrontPage = graphicast.find('FrontPage').text
		order = graphicast.find('order').text
		radar = graphicast.find('radar').text
		title = graphicast.find('title').text
		description = graphicast.find('description').text
		SmallImage = graphicast.find('SmallImage').text
		FullImage = graphicast.find('FullImage').text
		ImageLoop = graphicast.find('ImageLoop').text
		graphicNumber = graphicast.find('graphicNumber').text
		
		if isValid(StartTime, EndTime, FrontPage):
			html_images += "<b>" + str(title) + "</b><br>" + str(description) + "<br>"
			
			if radar == "1":
				html_images += "<img src=" + "\"" + ImageLoop + "\"" + "><br><br>"
			else:
				html_images += "<img src=" + "\"" + FullImage + "\"" + "><br><br>"
				
			#urllib.urlretrieve(SmallImage, "image_" + graphicNumber + ".jpg")


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
			Graphicast_Address = str(raw_input("Enter web address of Graphicast XML: "))
			emailSubject = str(raw_input("Enter default email subject: "))
			gmailUsername = str(raw_input("Enter Gmail username: "))
			gmailPassword = str(raw_input("Enter Gmail password: "))
			emailTo = str(raw_input("Enter email to recieve notifications: "))
			
			if os.path.isfile(base_path + "/config.ini"):
				os.remove(base_path + "/config.ini")
			cfgfile = open(base_path + "/config.ini",'w')
			
			# add the settings to the structure of the file, and lets write it out...
			Config.add_section('UserConfig')
			Config.set('UserConfig','graphicast_address',Graphicast_Address)
			Config.set('UserConfig','emailSubject',emailSubject)
			Config.set('UserConfig','gmailUsername',gmailUsername)
			Config.set('UserConfig','gmailPassword',gmailPassword)
			Config.set('UserConfig','emailTo',emailTo)
			Config.set('UserConfig','last_xml_date'," ")
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
	Graphicast_Address = Config.get(section, 'graphicast_address')
	Last_XML_Date = Config.get(section, 'last_xml_date')
	emailSubject = Config.get(section, 'emailSubject')
	gmailUsername = Config.get(section, 'gmailUsername')
	gmailPassword = Config.get(section, 'gmailPassword')
	emailTo = Config.get(section, 'emailTo')
	
	xml = base_path + "/graphicast.xml"
	
	#urllib.urlretrieve("http://www.srh.noaa.gov/images/fxc/oun/graphicast/graphicast.xml", xml)
	urllib.urlretrieve(Graphicast_Address, xml)
	
	tree = ET.parse(xml)
	root = tree.getroot()
	
	created = root.find('head').find('product').find('creation-date').text
	
	if (created != Last_XML_Date) or Force:
		
		#Save XML Date
		cfgfile = open(base_path + "/config.ini",'w')
		Config.set('UserConfig','last_xml_date',created)
		Config.write(cfgfile)
		cfgfile.close() 
	
		parseXML(root)
		sendEmail(emailSubject, emailTo, gmailUsername, gmailPassword)
		os.remove (xml)

		
		
#Start here
html_images = ""
base_path = sys.path[0]
main(sys.argv)