import click
import pickle
import os
import numpy as np
from const import *
import multiprocessing
from multiprocessing import Queue
import time
from models.vae import ConvVAE
from models.lstm import LSTM
from models.controller import Controller
from models.helper import load_model, save_checkpoint
from lib.controller_utils import CMAES
from lib.play_utils import VAECGame




def train_controller(current_time):
    current_version = 0
    current_time = str(current_time)
    current_best = 0
    game = GAMES["SONIC-1"]
    levels = LEVELS[game]
    level = np.random.choice(levels)
    max_timesteps = MAX_TIMESTEPS
    result_queue = Queue()

    vae, _ = load_model(current_time, -1, model="vae")
    if not vae:
        vae = ConvVAE((HEIGHT, WIDTH, 3), LATENT_VEC).to(DEVICE)
    
    lstm, _ = load_model(current_time, -1, model="lstm")
    if not lstm:
        lstm = LSTM(HIDDEN_UNITS, LATENT_VEC,\
                    NUM_LAYERS, GAUSSIANS, HIDDEN_DIM).to(DEVICE)
    
    checkpoint, solver = load_model(current_time, -1, model="controller")
    best_controller = Controller(LATENT_VEC, HIDDEN_UNITS * NUM_LAYERS * 2,
                                    ACTION_SPACE).to(DEVICE)
    if solver:
        current_version = checkpoint['version']
    else:
        solver = CMAES(LATENT_VEC + HIDDEN_UNITS * NUM_LAYERS * 2,
                    sigma_init=SIGMA_INIT,
                    popsize=POPULATION)

    while True:
        solutions = solver.ask()
        fitlist = np.zeros(POPULATION)
        left = 0
        if current_best > SCORE_CAP:
            level = np.random.choice(levels)

        print("[CONTROLLER] Current level is: %s" % level)
        while left < POPULATION:
            jobs = []
            todo = PARALLEL if left + PARALLEL <= POPULATION else (left + PARALLEL) % left
            print("[CONTROLLER] Starting new batch")
            for job in range(todo):
                idx = left + job
                controller = Controller(LATENT_VEC, HIDDEN_UNITS * NUM_LAYERS * 2, ACTION_SPACE).to(DEVICE)
                new_w = torch.tensor(solutions[idx], dtype=torch.float, device=DEVICE)
                controller.state_dict()['fc1.weight'].data.copy_(new_w)
                jobs.append(VAECGame(current_time, idx, vae, lstm, controller, \
                        game, level, result_queue, max_timesteps))
            for p in jobs:
                p.start()
            for p in jobs:
                p.join()
            left = left + PARALLEL
            print("[CONTROLLER] Done with batch")
        times = []
        for i in range(POPULATION):
            result = result_queue.get()
            keys = list(result.keys())
            result = list(result.values())
            fitlist[keys[0]] = result[0][0]
            times.append(result[0][1])


        print("[CONTROLLER] Total duration for generation: %.3f seconds, average duration:"
            " %.3f seconds per process, %.3f seconds per run" % ((np.sum(times), \
                    np.mean(times), np.mean(times) / REPEAT_ROLLOUT)))
        solver.tell(fitlist)
        new_results = solver.result()
        current_best = new_results[1]
        print("[CONTROLLER] Creating generation: {} ...".format(current_version + 1))
        print("[CONTROLLER] Current score: {}".format(new_results[2]))
        print("[CONTROLLER] Best score ever: {}\n".format(new_results[1]))
        new_w = torch.tensor(new_results[0], dtype=torch.float, device=DEVICE)
        best_controller.state_dict()['fc1.weight'].data.copy_(new_w)
        current_version += 1
        max_timesteps += TIMESTEP_DECAY
        state = { 'version': current_version }
        save_checkpoint(best_controller, "controller", state, current_time)
        dir_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), \
                    'saved_models', current_time, "{}-solver.pkl".format(current_version))
        pickle.dump(solver, open(dir_path, 'wb'))

        
@click.command()
@click.option("--folder", default=-1)
def main(folder):
    multiprocessing.set_start_method('spawn')
    if folder == -1:
        current_time = int(time.time())
    else:
        current_time = folder
    train_controller(current_time)
        


if __name__ == "__main__":
    main()