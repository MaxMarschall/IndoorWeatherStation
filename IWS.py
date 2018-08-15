import time,pytz,logging,gps,Adafruit_MCP3008,VL53L0X,urllib2,NDIR,Adafruit_IO
import datetime as dt
from Adafruit_BME280 import *
from sgp30 import SGP30
from smbus import SMBus

#General
logging.basicConfig(filename='log.log',filemode='w',level=logging.INFO)
logging.info('START: %s'%dt.datetime.utcnow())
smbus = SMBus(1)
lastmin = dt.datetime.now().minute
mcp = Adafruit_MCP3008.MCP3008(clk=18,cs=25,miso=23,mosi=24)
res = 60.0
count = 1
sums = [0,0,0,0,0,0,0,0]
num = 0

###IO
io = Adafruit_IO.Client('maxgmarschall','4ad18aff43cb4d9e8084855bb5b9be2f')
try:
    urllib2.urlopen('http://www.google.com').close()
    internet = True
except urllib2.URLError:
    internet = False
print('Internet: %s'%internet)
logging.info('Internet: %s'%internet)

if internet:
    f0 = io.feeds('wearable')
    f1 = io.feeds('temperature')
    f2 = io.feeds('humidity')
    f3 = io.feeds('wind')
    f4 = io.feeds('luminosity')
    f5 = io.feeds('noise')
    f6 = io.feeds('co2')
    f7 = io.feeds('voc')
    f8 = io.feeds('distance')
    location = io.feeds('gps')
logging.info('IO setup done')

###GPS
session = gps.gps('localhost','2947')
session.stream(gps.WATCH_ENABLE|gps.WATCH_NEWSTYLE)
lastlat,lastlon,lastalt,lastspe = ('None','None','None','None')
replacegps = True

###TSL
try:
    smbus.write_byte_data(0x39, 0x00 | 0x80, 0x03)
    smbus.write_byte_data(0x39, 0x01 | 0x80, 0x02)
    time.sleep(0.5)
except:
    print('tsl not connected')
    logging.info('tsl not connected')

###BME
try: bme = BME280(t_mode=BME280_OSAMPLE_8, p_mode=BME280_OSAMPLE_8, h_mode=BME280_OSAMPLE_8)
except:
    print('bme not connected')
    logging.info('bme not connected')
    
###Rev C
analogPinForRV = 1
analogPinForTMP = 2
zeroWindAdjustment =  -.1

###MAX4466
sampleWindow = 2

###MH-Z16
try:
    mh = NDIR.Sensor(0x4D)
    mh.begin()
except:
    print('mh not connected')
    logging.info('mh not conected')

###VL53L0X
tof = VL53L0X.VL53L0X()
tof.start_ranging(VL53L0X.VL53L0X_BETTER_ACCURACY_MODE)

logging.info('Sensor setup done')

with SGP30(smbus) as chip:
    while True:
        tim,lat,lon,alt,spe,T,H,W,L,N,C,V,D = (dt.datetime.now(tz=pytz.timezone("Europe/Berlin")),'None','None','None','None',0,0,0,0,0,0,0,0)
        
        ###GPS
        try:
            if not session:
                session = gps.gps('localhost','2947')
                session.stream(gps.WATCH_ENABLE|gps.WATCH_NEWSTYLE)
            report = session.next()
            if report['class']=='TPV':
                if hasattr(report,'lat'): lat = round(report.lat,6)
                if hasattr(report,'lon'): lon = round(report.lon,6)
                if hasattr(report,'alt'): alt = report.alt
                if hasattr(report,'speed'): spe = report.speed
        except KeyError:
            print('gps keyerror')
            logging.info('gps keyerror')
        except KeyboardInterrupt: quit()
        except StopIteration: session = None
        except:
            print('gps')
            logging.info('gps')
        if lat=='None' and replacegps==True:
            lat,lon,alt,spe = (lastlat,lastlon,lastalt,lastspe)
            replacegps = False
        else: replacegps = True
        lastlat,lastlon,lastalt,lastspe = (lat,lon,alt,spe)

        ###BME
        try:
            if not bme:
                try: bme = BME280(t_mode=BME280_OSAMPLE_8, p_mode=BME280_OSAMPLE_8, h_mode=BME280_OSAMPLE_8)
                except: pass
            T = bme.read_temperature()
            H = bme.read_humidity()
        except:
            print('bme')
            logging.info('bme')

        ###TSL
        try:
            data = smbus.read_i2c_block_data(0x39, 0x0C | 0x80, 2)
            data1 = smbus.read_i2c_block_data(0x39, 0x0E | 0x80, 2)
            ch0 = data[1] * 256 + data[0]
            ch1 = data1[1] * 256 + data1[0]
            L = ch0-ch1
        except:
            print('tsl')
            logging.info('tsl')
        
        ###Rev C
        try:
            TMP_Therm_ADunits = mcp.read_adc(analogPinForTMP)
            RV_Wind_ADunits = mcp.read_adc(analogPinForRV)
            RV_Wind_Volts = (RV_Wind_ADunits * 0.0048828125)
            TempCtimes100 = (0.005 * (float(TMP_Therm_ADunits) * float(TMP_Therm_ADunits))) - (16.862 * float(TMP_Therm_ADunits)) + 9075.4
            zeroWind_ADunits = -0.0006 * (float(TMP_Therm_ADunits) * float(TMP_Therm_ADunits)) + 1.0727 * float(TMP_Therm_ADunits) + 47.172
            zeroWind_volts = (zeroWind_ADunits * 0.0048828125) - zeroWindAdjustment 
            try: WindSpeed_MPH =  pow(((RV_Wind_Volts - zeroWind_volts) /.2300) , 2.7265)
            except:
                WindSpeed_MPH = 0.0
                print('negative wind speed')
                logging.info('negative wind speed')
            W = float(WindSpeed_MPH*0.44704)
        except:
            print('rev c')
            logging.info('rev c')
        
        ###MAX4466
        try:
            signalmax = 0
            signalmin = 1024
            startloop = time.time()
            ncount = 0
            while (time.time()-startloop)<sampleWindow:
                sample = mcp.read_adc(0)
                if sample<1024:
                    if sample>signalmax: signalmax = sample
                    if sample<signalmin: signalmin = sample
            peaktopeak = signalmax-signalmin
            N = (peaktopeak*3.3)/1024
        except:
            print('max')
            logging.info('max')
        
        ###MH-Z16
        try:
            mhcount = 0
            while mhcount<10:
                if C==0:
                    try:
                        C = mh.getCO2()
                        if C==None: C = 0
                    except: pass
                if C!=0: break
                mhcount+=1
        except:
            print('mh')
            logging.info('mh')
        
        ###SGP30
        try:
            aq = chip.measure_air_quality()
            V = aq.voc_ppb
        except:
            print('sgp')
            logging.info('sgp')
        
        ###VL53L0X
        start = time.time()
        try:
            D = tof.get_distance()
        except:
            print('vl')
            logging.info('vl')
        if (time.time()-start)>2:
            try:
                tof.stop_ranging()
                tof = VL53L0X.VL53L0X()
                tof.start_ranging(VL53L0X.VL53L0X_BETTER_ACCURACY_MODE)
            except:
                print('vlinit')
                logging.info('vlinit')
        
        ###Add to sums
        sums[0]+=float(T)
        sums[1]+=float(H)
        sums[2]+=float(W)
        sums[3]+=float(L)
        sums[4]+=float(N)
        sums[5]+=float(C)
        sums[6]+=float(V)
        sums[7]+=float(D)
        num+=1
        
        ###Print to terminal
        if tim!='None': temptim = tim.strftime('%y.%m.%d %H:%M:%S')
        else: temptim = tim
        if lat!='None': templat = round(float(lat),6)
        else: templat = 0
        if lon!='None': templon = round(float(lon),6)
        else: templon = 0
        if alt!='None': tempalt = round(float(alt),1)
        else: tempalt = 0
        if spe!='None': tempspe = round(float(spe),2)
        else: tempspe = 0
        if T!=0: T = round(T,2)
        if H!=0: H = round(H,2)
        if W!=0: W = round(W,2)
        if L!=0: L = round(L)
        if N!=0: N = round(N,2)
        if C!=0: C = round(C)
        if V!=0: V = round(V)
        if D!=0: D = round(D)
        print('Time: %s  |  Lat: %.6f  |  Lon: %.6f   |   Alt: %.1f  |  Spe: %.2f  |  T: %.2f  |  H: %.2f  |  W: %.2f  |  L: %d  |  N: %.2f  |  C: %d  |  V: %d  |  D: %d'%(temptim,templat,templon,tempalt,tempspe,T,H,W,L,N,C,V,D))
        
        ###Write line
        if dt.datetime.now().minute!=lastmin:
            T = round(sums[0]/num,2)
            H = round(sums[1]/num,2)
            W = round(sums[2]/num,2)
            L = int(round(sums[3]/num))
            N = round(sums[4]/num,2)
            C = int(round(sums[5]/num))
            V = int(round(sums[6]/num))
            D = int(round(sums[7]/num))
            l = '%s,%.6f,%.6f,%.1f,%.2f,%.2f,%.2f,%.2f,%.d,%.2f,%.d,%.d,%.d\n'%(tim,templat,templon,tempalt,tempspe,T,H,W,L,N,C,V,D)
            print('%s\n'%l[:-1])
            with open('/home/pi/DataLogging/DATA/'+str('00_'+str(dt.date.today()))+'.csv','a') as log: log.write(l)
            lastmin = dt.datetime.now().minute
            
            try:
                urllib2.urlopen('http://www.google.com').close()
                internet = True
            except urllib2.URLError:
                internet = False
                print('\nNo internet')
                logging.info('No internet')
            
            if internet:
                try: a = f0.key
                except:
                    f0 = io.feeds('wearable')
                    f1 = io.feeds('temperature')
                    f2 = io.feeds('humidity')
                    f3 = io.feeds('wind')
                    f4 = io.feeds('luminosity')
                    f5 = io.feeds('noise')
                    f6 = io.feeds('co2')
                    f7 = io.feeds('voc')
                    f8 = io.feeds('distance')
                
                try:
                    io.send(f0.key,l[:-1])
                    io.send(f1.key,T)
                    io.send(f2.key,H)
                    io.send(f3.key,W)
                    io.send(f4.key,L)
                    io.send(f5.key,N)
                    io.send(f6.key,C)
                    io.send(f7.key,V)
                    io.send(f8.key,D)
                    io.send_location_data(location.key,spe,lat,lon,alt)
                    sums = [0,0,0,0,0,0,0,0]
                    num = 0
                    count+=1
                    logging.info(l)
                except Adafruit_IO.errors.ThrottlingError:
                    print('ThrottlingError')
                    logging.info('ThrottlingError')
                    time.sleep(35)  
##                except ConnectionError:
##                    print('ConnectionError')
##                    logging.info('ConnectionError')
##                    time.sleep(35)                   
##                except:
##                    print('something went wrong')
##                    logging.info('something went wrong')
tof.stop_ranging()
