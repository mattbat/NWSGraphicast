# NWSGraphicast

This script emails a user the latest Graphicast forecast images provided by the National Weather Service (NWS).


<NOTE: The following instructions need to be updated>
---

1. Must configure prior to running
	* python main.py -c
	* **NWS Office Abbreviation**  
	   Most NWS offices are supported.  
	   Find your local NWS office abbreviation here: http://www.wrh.noaa.gov/wrh/forecastoffice_tab.php  
	   Example: 'OUN' 
	     
	* **Gmail Username**  
	   The gmail username used to send the email.
	   Only Gmail is supported for sending at this time.  
	   Example: `USERNAME@gmail.com`  
	   
	   Gmail security settings must be set to "Allow Less Secure Apps" for sign-in.  
	   The configuration option is located here: https://myaccount.google.com/security?utm_source=OGB#signin  
	   It is *highly* recommended that you created a dedicated account to for this purpose since it must allow this insecure login setting.
	 
	* **Gmail Password**  
	   The gmail password used to send the email.  
	   Only Gmail is supported for sending at this time.  
	   Example: `PASSWORD`     
	   
	* **TO Email**  
	   The email address to receive the notifications.  
	   Example: `USERNAME@domain.com`   
	   	
	
