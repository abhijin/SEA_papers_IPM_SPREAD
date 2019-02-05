import os
import numpy as np
import math
import pdb
import sys
import copy
import time
import argparse
import logging
import pickle
from random import *

from cellular_automata import Cell, CA
from shutil import rmtree
import pandas as pd
try:
   import shapefile as shp
   import matplotlib.pyplot as plt
   from matplotlib.patches import Rectangle
except:
   pass
from create_ca import load_object, dump_object

# hardcoded stuff
GRID_ADC_ID_MAP='../data/south_east_asia_adc_id_p25xp25.csv'


def update_ca_plus(index,ca,cell, infectivity, invaded, infect_loc, moore_nbd,\
      time,suit_thresh,alpha_sd, alpha_fm, alpha_mm): 
    suit = suitability(infectivity,time,suit_thresh)
    sd_prob = suit * (1-math.exp(-alpha_sd *natural_inf(cell['moore'],moore_nbd, invaded, time)))
    if cell['local']!=None:
        fm_prob = suit * (1-math.exp(-alpha_fm *local_inf(cell['local'],infect_loc, time)))
        mm_prob = suit * (1-math.exp(-alpha_mm *long_dist_inf(ca.network, cell,infect_loc, time)))
    else:
       fm_prob=0
       mm_prob=0

    if random() < sd_prob:
       return 'E'
    elif random() < fm_prob:
       return 'E'
    elif random() < mm_prob:
       return 'E'
    else:
       return 'S'

def suitability(infectivity,time,suit_thresh):
   if infectivity[time] > suit_thresh: 
      suit = 1 
   else: 
      suit = 0 
   return suit

def local_inf(loc, infect_dict, time):
   try: inf = infect_dict[loc][time] 
   except: inf = 0 
   return inf

def long_dist_inf(network, cell,loc_dict, time):
   nbrsFlows=network[(network['cell_id_y']==cell['local']) &\
      (network['cell_id_x']!=cell['local']) &\
      (network['month']==time+1)]
   
   sum = 0 
   for index,row in nbrsFlows.iterrows(): 
      src=row[4]
      flow=row[2]
      try: 
         sum += flow * loc_dict[src][time] 
      except: continue 
   return sum

def natural_inf(nbd, max_nbd, invaded, time):
    sum = 0
    for cell in nbd:
       try: 
          infect = invaded[cell[0]][time] 
       except: continue 
       if cell[1] <= max_nbd: 
          sum += infect
    return sum

def create_region_grid_map(csvfile=GRID_ADC_ID_MAP):
    df = pd.read_csv(csvfile)
    region_to_grid = {}
    grid_to_region = {}
    for index, row in df.iterrows():
        region_id = row['admin1_iso']
        cell_id = row['cell_id']
        try:
            region_to_grid[region_id].append(cell_id)
            grid_to_region[cell_id].append(region_id)
        except:
            region_to_grid[region_id]=[cell_id]
            grid_to_region[cell_id]=[region_id]
    return region_to_grid,grid_to_region

def create_country_grid_map(csvfile='../data/grid_country_map.csv'):
    df = pd.read_csv(csvfile)
    country_to_grid = dict()
    for index, row in df.iterrows():
        country_id = row['adc_id']
        cell_id = row['#cell_id']
        if not country_id in country_to_grid:
            country_to_grid[country_id] = [cell_id]
        else:
            country_to_grid[country_id].append(cell_id)
    return country_to_grid

def infectivity(cell_season_data):
    w1 = .9
    w2 = .75
    w3 = .65
    return [w1 * cell_season_data[time+1] + w2 * cell_season_data.iloc[13+time] + w3 * cell_season_data.iloc[25+time] for time in range(12)]

def computeInfectivity(season_data):
   wTom = .9
   wEgg = .75
   wPot = .65
   cols=[x for x in xrange(1,13)]
   infectivity=season_data
   for m in xrange(1,13):
      infectivity[m]=wTom*infectivity['T%d' %m]\
            + wEgg*infectivity['E%d' %m]\
            + wPot*infectivity['P%d' %m]
   # normalize
   infectivity=infectivity[cols]
   infectivity=infectivity/max(infectivity.max())

   return infectivity

def run_ca(sim_runs, ca, seed, start_month, step, output, grid_to_region,\
      step_scale, moore_nbd, func_name, season_file,suit_thresh,\
      exp_delay,alpha_sd,alpha_fm,alpha_mm):
    season_data = pd.read_csv(season_file, index_col='cell_id')
    prob_dict = {}
    exp_delay_count={}
    border = True
    possibles = globals().copy()
    possibles.update(locals())
    ca_func = possibles.get(func_name)
    system_state = list()
    initial_state = record_output(ca)
    system_state.append(initial_state)
    simulationSteps=int(step/step_scale) # step is always in months
    susceptible = {}

    infectivity=computeInfectivity(season_data)
    for c in ca.cells:
      prob_dict[c] = [0] * simulationSteps 
    
    for run in range(sim_runs):
        # reset everything
        infect_loc = {}
        invaded = {}
        for c in ca.cells:
           ca.cells[c].state='S'
           ca.cells[c].time=-1
    
        # set seed
        for s in seed:
            ca.cells[int(s)].state = 'I'
            ca.cells[int(s)].time = 0
            infCell=infectivity.ix[int(s)].tolist()
            invaded[int(s)] = infCell
            try: 
               loc = ca.localities[int(s)]
               if type(loc)==list:
                  loc=int(s)
               try: 
                  for m in xrange(12): 
                     infect_loc[loc][m] += infCell[m]
               except:
                  infect_loc[loc] = infCell
            except: 
               pass
    
        system_state = list()
        initial_state = record_output(ca)
        system_state.append(initial_state)
        simulationSteps=int(step/step_scale) # step is always in months
        susceptible = {} 
    
        print 'simulation: ' + str(run)
        for i in range(simulationSteps):
            time = int(i*step_scale)
            # month goes from 1 to 12, but for update_ca_plus, it is 0 to 11
            month=(time+start_month-1)%12+1
            print 'time: %d, month: %d' %(time,month)
            new_infect = []
            new_exposed = []
            for index, cell in ca.cells.items():
                #AA: A hack for speeding up simulations
                #AA: choosing only Bangladesh cells
                #AA: CAUTION: will have boundary effects. Fortunately, major areas are in the center
                try:
                    if not ('BD-' in grid_to_region[index][0]):
                        continue
                except:
                #AA: There are some nans. Need to investigate
                    continue

                # extract locality
                try: 
                   loc = ca.localities[index]
                   if type(loc) == list:  #AA: needs to be changed
                      loc=index
                except: 
                   loc=None

                if time == 0: 
                   susceptible[index] = {'moore':cell.neighbors, 'local':loc}

                try:
                   infectivity.ix[index]
                except KeyError:
                   continue

                infCell=infectivity.ix[index].tolist()
                
                if cell.state == 'I':
                   continue

                if cell.state == 'E':
                   exp_delay_count[index]-=1
                   if exp_delay_count[index]!=0:
                      continue
                   invaded[index] = infCell
                   new_infect.append(int(index)) 
                   del exp_delay_count[index]

                   if loc is not None:
                      try:
                         for m in xrange(12): 
                            infect_loc[loc][m] += infCell[m]
                      except KeyError:
                         infect_loc[loc] = infCell
                   continue
    
                new_state = update_ca_plus(index,ca,susceptible[index], infCell, \
                   invaded, infect_loc, moore_nbd, month-1,suit_thresh, \
                   alpha_sd,alpha_fm,alpha_mm)
    
                if new_state == 'E':
                   new_exposed.append(index)
                   exp_delay_count[index]=exp_delay
                   del susceptible[index]
            for value in new_infect:
               ## if "PH-" in grid_to_region[value][0]:
               ##    pdb.set_trace()
               ca.cells[value].state = 'I'
               ca.cells[value].time = time
            for value in new_exposed:
                ca.cells[value].state = 'E'
    
        for index, cell in ca.cells.items():
            if cell.time >= 0: 
               prob_dict[index][cell.time] += 1 
       
    with open(output,'w') as f:
       lineStr=['cell_id'] + ['%d' %x for x in\
             xrange(start_month,simulationSteps+start_month)]
       f.write(','.join(lineStr)+'\n')
       for ele in prob_dict:
          lineStr=str(ele)
          for i in xrange(simulationSteps):
             lineStr+=',%.3f' %(prob_dict[ele][i]/float(sim_runs))
          f.write(lineStr+'\n')

def gen_seed(ca, region_to_grid, seed_file):
    region_df = pd.read_csv(seed_file)
    #south_america_df = pd.read_csv('../data/south_american_countries.csv')
    #country_to_grid = create_country_grid_map()
    invaded_region = region_df['#cell_id']
    #south_america = south_america_df['adc_id']
    seeds = list()
    #print region_df
    for seed in invaded_region:
       seeds.append(seed)

    ## for r in invaded_region:
    ##     for seed in region_to_grid[r]:
    ##         seeds.append(seed)

    ## for sm in south_america:
    ##     for seed in country_to_grid[sm]:
    ##         seeds.append(seed)
    return seeds

## def create_seed_file(grid_to_region,seed_file):
##     df = pd.DataFrame(columns = ['#cell_id','adc_id','country'])
##     # regions is list
##     region_df = pd.read_csv(GRID_ADC_ID_MAP)
##     for index, cell in region_df.iterrows():
##        id = cell['#cell_id']
##        country = cell['admin_name']
##        if type(country) != str:
##            continue
##        if country == 'BD-F':
##            adc_id = grid_to_region[id][0]
##            df = df.append({'#cell_id':id, 'adc_id':adc_id, 'country': str(cell['admin_name'])[:2]}, ignore_index = True)
##     df.to_csv(seed_file, index = False)



def record_output(ca):
    result = list()
    for index, cell in ca.cells.items():
        if cell.state == 'S':
            result.append(0)
        elif cell.state == 'E':
            result.append(1)
        elif cell.state == 'I':
            result.append(2)
    return result



if __name__ == "__main__":
   # read in arguments
   parser=argparse.ArgumentParser(
     formatter_class=argparse.RawTextHelpFormatter)

   parser.add_argument("--grid_file",help="Pickle file created by 'create_ca.py'.", default="ca_model_moore_6_filled.pkl")
   parser.add_argument("--seed_file",help="File chosen to seed", default="../data/seed_files/seed_Johor.csv")
   parser.add_argument("-o", "--output", default="out/output.csv")
   parser.add_argument("-n", "--time_steps", help="in months", default=16, type=int)
   parser.add_argument("--sim_runs", default = 10, type = int)
   parser.add_argument("-s", "--start_month", help="start month for simulations", default=1, type=int)
   parser.add_argument("-m", "--moore", default=3, type=int)
   parser.add_argument("--suitability_threshold", default=0, type=float)
   parser.add_argument("--exp_delay", default=1, type=float)
   parser.add_argument("--alpha_sd", default = 1, type = float)
   parser.add_argument("--alpha_fm", default = 1, type = float)
   parser.add_argument("--alpha_mm", default = 1, type = float)
   parser.add_argument("-v", "--verbose", action="store_true")
   # AA: remove this
   parser.add_argument("-f", "--function", default="update_ca_plus", type = str)
   #AA: need to be taken care of in fill_data
   parser.add_argument("--season_file", default = "../../production/obj/ca_seasonal_production.csv", type = str)
   parser.add_argument("--step_scale", default=1, type=float,
         help='scaling factor to obtain simulation time steps from \
         time_steps; 1 means simulation proceeds in one month steps, 0.5 means 15 days')
   args=parser.parse_args()

   # set logger
   if args.verbose:
      logging.basicConfig(level=logging.DEBUG)
   else:
      logging.basicConfig(level=logging.INFO)

   # print configuration
   print """==================================================
Input:
==================================================
grid file: %s
seed file: %s
out file: %s
time steps: %d
simulation runs: %d
start month: %d
moore range: %d
suitability threshold: %d
exposed delay: %d
alpha_sd: %g
alpha_fm: %g
alpha_mm: %g
==================================================""" %(\
args.grid_file,\
args.seed_file,\
args.output,\
args.time_steps,\
args.sim_runs,\
args.start_month,\
args.moore,\
args.suitability_threshold,\
args.exp_delay,\
args.alpha_sd,\
args.alpha_fm,\
args.alpha_mm)

   print 'loading ' + args.grid_file
   ca = load_object(args.grid_file)
   print 'loaded'

   start_time=time.time()
   print "running ca..."
   region_to_grid,grid_to_region = create_region_grid_map()
   

   #create_seed_file(grid_to_region, args.seed_file)
   seeds = gen_seed(ca, region_to_grid, args.seed_file)

   output = args.output
   # output = "single_city_seed/output_moore_" + str(args.moore) + ".csv"

   run_ca(args.sim_runs, ca, seeds, args.start_month, args.time_steps,\
         output, grid_to_region, args.step_scale, args.moore,\
         args.function, args.season_file,args.suitability_threshold,\
         args.exp_delay,args.alpha_sd,args.alpha_fm,args.alpha_mm)
   fill_data_time = time.time()
   print "simulation ended. Time used: %.2f minutes" %((fill_data_time-start_time)/60)

