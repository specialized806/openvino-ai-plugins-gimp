#!/usr/bin/env python3
# Copyright(C) 2022-2023 Intel Corporation
# SPDX - License - Identifier: Apache - 2.0

import os
import json
import sys
import socket
import cv2
import ast
import traceback
import logging as log
from pathlib import Path
import time 
import random
import torch
        
from PIL import Image
import numpy as np
import psutil
import threading
sys.path.extend([os.path.join(os.path.dirname(os.path.realpath(__file__)), "openvino_common")])
sys.path.extend([os.path.join(os.path.dirname(os.path.realpath(__file__)), "..","tools")])

from gimpopenvino.plugins.openvino_utils.tools.tools_utils import get_weight_path, SDOptionCache

from diffusers.schedulers import DDIMScheduler, LMSDiscreteScheduler, LCMScheduler, EulerDiscreteScheduler
from models_ov.stable_diffusion_engine import StableDiffusionEngineAdvanced, StableDiffusionEngine, LatentConsistencyEngine, StableDiffusionEngineReferenceOnly
from models_ov.stable_diffusion_engine_inpainting import StableDiffusionEngineInpainting
from models_ov.stable_diffusion_engine_inpainting_genai import StableDiffusionEngineInpaintingGenai
from models_ov.stable_diffusion_engine_inpainting_advanced import StableDiffusionEngineInpaintingAdvanced
from models_ov.controlnet_openpose import ControlNetOpenPose
from models_ov.controlnet_canny_edge import ControlNetCannyEdge
from models_ov.controlnet_scribble import ControlNetScribble, ControlNetScribbleAdvanced
from models_ov.controlnet_openpose_advanced import ControlNetOpenPoseAdvanced
from models_ov.controlnet_cannyedge_advanced import ControlNetCannyEdgeAdvanced

from models_ov import (
    stable_diffusion_engine,
    stable_diffusion_engine_genai,
    stable_diffusion_engine_inpainting_genai,
    stable_diffusion_engine_inpainting,
    stable_diffusion_engine_inpainting_advanced,
    stable_diffusion_3,
    controlnet_openpose,
    controlnet_canny_edge,
    controlnet_scribble,
    controlnet_openpose_advanced,
    controlnet_cannyedge_advanced
)


HOST = "127.0.0.1"  # Standard loopback interface address (localhost)
PORT = 65432  # Port to listen on (non-privileged ports are > 1023)

log.basicConfig(format='[ %(levelname)s ] %(message)s', level=log.DEBUG, stream=sys.stdout)

def progress_callback(i, conn):
    tosend = bytes(str(i), 'utf-8')
    conn.sendall(tosend)

def run(model_name, available_devices, power_mode):
    weight_path = get_weight_path()
    scheduler = EulerDiscreteScheduler(
        beta_start=0.00085,
        beta_end=0.012,
        beta_schedule="scaled_linear"
    )

    log.info('Model Name: %s', model_name) 

    model_paths = {
        "sd_1.4": ["stable-diffusion-ov", "stable-diffusion-1.4"],
        "sd_1.5_square_lcm": ["stable-diffusion-ov", "stable-diffusion-1.5", "square_lcm"],
        "sdxl_base_1.0_square": ["stable-diffusion-ov", "stable-diffusion-xl", "square_base"],
        "sdxl_turbo_square": ["stable-diffusion-ov", "stable-diffusion-xl", "square_turbo"],
        "sd_1.5_portrait": ["stable-diffusion-ov", "stable-diffusion-1.5", "portrait"],
        "sd_1.5_square": ["stable-diffusion-ov", "stable-diffusion-1.5", "square"],
        "sd_1.5_square_int8": ["stable-diffusion-ov", "stable-diffusion-1.5", "square_int8"],
        "sd_1.5_square_int8a16": ["stable-diffusion-ov", "stable-diffusion-1.5", "square_int8"],
        "sd_3.0_med_diffuser_square": ["stable-diffusion-ov", "stable-diffusion-3.0-medium", "square_diffusers" ],
        "sd_3.5_med_turbo_square": ["stable-diffusion-ov", "stable-diffusion-3.5-medium", "square_turbo" ],
        "sd_1.5_landscape": ["stable-diffusion-ov", "stable-diffusion-1.5", "landscape"],
        "sd_1.5_portrait_512x768": ["stable-diffusion-ov", "stable-diffusion-1.5", "portrait_512x768"],
        "sd_1.5_landscape_768x512": ["stable-diffusion-ov", "stable-diffusion-1.5", "landscape_768x512"],
        "sd_1.5_inpainting": ["stable-diffusion-ov", "stable-diffusion-1.5", "inpainting"],
        "sd_1.5_inpainting_int8": ["stable-diffusion-ov", "stable-diffusion-1.5", "inpainting_int8"],
        "sd_2.1_square_base": ["stable-diffusion-ov", "stable-diffusion-2.1", "square_base"],
        "sd_2.1_square": ["stable-diffusion-ov", "stable-diffusion-2.1", "square"],
        "sd_3.0_square": ["stable-diffusion-ov", "stable-diffusion-3.0"],
        "controlnet_referenceonly": ["stable-diffusion-ov", "controlnet-referenceonly"],
        "controlnet_openpose": ["stable-diffusion-ov", "controlnet-openpose"],
        "controlnet_canny": ["stable-diffusion-ov", "controlnet-canny"],
        "controlnet_scribble": ["stable-diffusion-ov", "controlnet-scribble"],
        "controlnet_openpose_int8": ["stable-diffusion-ov", "controlnet-openpose-int8"],
        "controlnet_canny_int8": ["stable-diffusion-ov", "controlnet-canny-int8"],
        "controlnet_scribble_int8": ["stable-diffusion-ov", "controlnet-scribble-int8"],
    }

    # Default path if model_name is not in the dictionary
    default_path = ["stable-diffusion-ov", "stable-diffusion-1.4"]
    default_config = {
        "power modes supported" : "no",
        "best performance" : ["GPU", "GPU","GPU", "GPU"]
    }
    model_path = os.path.join(weight_path, *model_paths.get(model_name, default_path))

    log.info('Initializing Inference Engine...')
    log.info('Model Path: %s', model_path)
    device_list = ["CPU"] * 5
    model_config_file_name = os.path.join(model_path, "config.json")
    
    try:
        if os.path.exists(model_config_file_name):
            with open(model_config_file_name, 'r') as file:
                model_config = json.load(file)
                if model_config['power modes supported'].lower() == "yes":
                    device_list = model_config[power_mode.lower()]
                else:
                    device_list = model_config['best performance']   
        else:
            with open(model_config_file_name,  'w') as file:
                json.dump(default_config, file, indent=4)
                device_list = default_config['best performance']

        for device in available_devices:
            if device.lower() == 'gpu.1':
                if power_mode.lower() == 'best power efficiency':
                    device_list = [d.replace('GPU', 'GPU.0') if isinstance(d, str) else d for d in device_list]
                else:
                    device_list = [d.replace('GPU', 'GPU.1') if isinstance(d, str) else d for d in device_list]
       
    except (KeyError, FileNotFoundError, json.JSONDecodeError) as e:
        log.error(f"Error loading configuration: {e}. Only CPU will be used.")

    engine = initialize_engine(model_name, model_path, device_list)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        # Enable address reuse to avoid 'Address already in use' errors
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        retries = 15
        while( retries > 0):
            try:
                s.bind((HOST, PORT))
                break
            except Exception as e:
                traceback.print_exc()
                retries = retries - 1
                print("Error in server binding. Retries left = ", retries)

                if retries > 0:
                   print("Waiting 5 seconds until next retry")
                   time.sleep(5)
                else:
                   print("Error in stable diffusion server binding. Out of retries.")

                   # Trigger exit of this server
                   s.close()  # Explicitly close the socket
                   os._exit(1)

        s.listen()
        s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s2.connect((HOST, 65433))
        s2.sendall(b"Ready")
        #print("Ready")
        while True:
            conn, addr = s.accept()
            with conn:
                while True:
                    #print("Waiting")
                    data = conn.recv(1024)

                    if data.decode() == "kill":
                        s.close()  # Explicitly close the socket
                        os._exit(0)
                    if data.decode() == "ping":
                        conn.sendall(data)
                        continue
                    if data.decode() == "model_name":
                        tosend = bytes(model_name, 'utf-8')
                        conn.sendall(tosend)
                        continue

                    if not data:
                        break
                    handle_client_data(data, conn, engine, model_name, model_path, scheduler)

def initialize_engine(model_name, model_path, device_list):
    if model_name == "sd_1.5_square_int8":
        log.info('Device list: %s', device_list)
        return stable_diffusion_engine.StableDiffusionEngineAdvanced(model=model_path, device=device_list)
    if model_name == "sd_3.0_square":
        device_list = ["GPU"]
        log.info('Device list: %s', device_list)
        return stable_diffusion_3.StableDiffusionThreeEngine(model=model_path, device=device_list)
    if model_name == "sd_1.5_inpainting":
        return stable_diffusion_engine_inpainting_genai.StableDiffusionEngineInpaintingGenai(model=model_path, device=device_list[0])
    if model_name in ("sd_1.5_square_lcm","sdxl_base_1.0_square","sdxl_turbo_square","sd_3.0_med_diffuser_square","sd_3.5_med_turbo_square"):
        return stable_diffusion_engine_genai.StableDiffusionEngineGenai(model=model_path,model_name=model_name,device=device_list)
    if model_name == "sd_1.5_inpainting_int8":
        log.info('Advanced Inpainting Device list: %s', device_list)
        return stable_diffusion_engine_inpainting_advanced.StableDiffusionEngineInpaintingAdvanced(model=model_path, device=device_list)
    if model_name == "controlnet_openpose_int8":
        log.info('Device list: %s', device_list)
        return controlnet_openpose_advanced.ControlNetOpenPoseAdvanced(model=model_path, device=device_list)
    if model_name == "controlnet_canny_int8":
        log.info('Device list: %s', device_list)
        return controlnet_cannyedge_advanced.ControlNetCannyEdgeAdvanced(model=model_path, device=device_list)
    if model_name == "controlnet_scribble_int8":
        log.info('Device list: %s', device_list)
        return controlnet_scribble.ControlNetScribbleAdvanced(model=model_path, device=device_list)
    if model_name == "controlnet_canny":
        return controlnet_canny_edge.ControlNetCannyEdge(model=model_path, device=device_list)
    if model_name == "controlnet_scribble":
        return controlnet_scribble.ControlNetScribble(model=model_path, device=device_list)
    if model_name == "controlnet_openpose":
        return controlnet_openpose.ControlNetOpenPose(model=model_path, device=device_list)
    if model_name == "controlnet_referenceonly":
        return stable_diffusion_engine.StableDiffusionEngineReferenceOnly(model=model_path, device=device_list)
    return stable_diffusion_engine.StableDiffusionEngine(model=model_path, device=device_list, model_name=model_name)

def handle_client_data(data, conn, engine, model_name, model_path, scheduler):
    if data.decode() == "kill":
        os._exit(0)
    if data.decode() == "ping":
        conn.sendall(data)
        return
    if data.decode() == "model_name":
        tosend = bytes(model_name, 'utf-8')
        conn.sendall(tosend)
        return
    try:
        weight_path = get_weight_path()
        option_cache_file = os.path.join(weight_path, "..", "gimp_openvino_run_sd.json")
        options = SDOptionCache(option_cache_file)

        prompt = options.get("prompt")
        negative_prompt = options.get("negative_prompt")
        init_image = options.get("initial_image")
        num_images = options.get("num_images")
        strength = options.get("strength")
        seed = options.get("seed")
        create_gif = False

        if model_name in ("sdxl_turbo_square","sd_3.5_med_turbo_square"):
            num_infer_steps = options.get("num_infer_steps_turbo")
            guidance_scale = options.get("guidance_scale_turbo")
        else:
            num_infer_steps = options.get("num_infer_steps")
            guidance_scale = options.get("guidance_scale")

        strength = 1.0 if init_image is None else strength
        log.info('Starting inference... ')
        log.info('Prompt: %s', prompt)

        if model_name != "sd_1.5_square_lcm":
            log.info('Strength: %s', strength)
            log.info('Negative Prompt: %s', negative_prompt)
        log.info('Inference Steps: %s', num_infer_steps)
        log.info('Number of Images: %s', num_images)
        log.info('Guidance Scale: %s', guidance_scale)
        
        log.info('Init Image: %s', init_image)

        if seed is not None:
            np.random.seed(int(seed))
            log.info('Seed: %s', seed)
        else:
            seed = random.randrange(4294967294)
            np.random.seed(int(seed))
            log.info('Random Seed: %s', seed)

        start_time = time.time()

        if model_name == "sd_1.5_inpainting" or model_name == "sd_1.5_inpainting_int8":
            output = engine(
                prompt=prompt,
                negative_prompt=negative_prompt,
                image_path=os.path.join(weight_path, "..", "cache1.png"),
                mask_path=os.path.join(weight_path, "..", "cache0.png"),
                scheduler=scheduler,
                strength=strength,
                num_inference_steps=num_infer_steps,
                guidance_scale=guidance_scale,
                callback=progress_callback,
                callback_userdata=conn
            )
        elif model_name == "controlnet_referenceonly":
            output = engine(
                prompt=prompt,
                negative_prompt=negative_prompt,
                image=Image.open(init_image),
                scheduler=scheduler,
                num_inference_steps=num_infer_steps,
                guidance_scale=guidance_scale,
                eta=0.0,
                create_gif=bool(create_gif),
                model=model_path,
                callback=progress_callback,
                callback_userdata=conn
            )
        elif "controlnet" in model_name: 
            output = engine(
                prompt=prompt,
                negative_prompt=negative_prompt,
                image=Image.open(init_image),
                scheduler=scheduler,
                num_inference_steps=num_infer_steps,
                guidance_scale=guidance_scale,
                eta=0.0,
                create_gif=bool(create_gif),
                model=model_path,
                callback=progress_callback,
                callback_userdata=conn
            )        
        elif model_name == "sd_1.5_square_lcm":        
            output = engine(
                 prompt=prompt,
                 negative_prompt=None,
                 num_inference_steps=num_infer_steps,
                 guidance_scale=guidance_scale,
                 seed=seed,
                 callback=progress_callback,
                 callback_userdata=conn,
            )
        elif "sdxl" in model_name:        
            output = engine(
                 prompt=prompt,
                 negative_prompt=None,
                 num_inference_steps=num_infer_steps,
                 guidance_scale=guidance_scale,
                 seed=seed,
                 callback=progress_callback,
                 callback_userdata=conn,
            )            
        elif "sd_3.0_med" in model_name or "sd_3.5_med" in model_name:
            if model_name =="sd_3.5_med_turbo_square":
                negative_prompt=None
            
            output = engine(
                 prompt=prompt,
                 negative_prompt=negative_prompt,
                 num_inference_steps=num_infer_steps,
                 guidance_scale=guidance_scale,
                 seed=seed,
                 callback=progress_callback,
                 callback_userdata=conn,
            )                           
        else:
            if model_name == "sd_2.1_square":
                scheduler = EulerDiscreteScheduler(
                    beta_start=0.00085,
                    beta_end=0.012,
                    beta_schedule="scaled_linear",
                    prediction_type="v_prediction"
                )
            model = model_path
            if "sd_2.1" in model_name:
                model = model_name

            output = engine(
                prompt=prompt,
                negative_prompt=negative_prompt,
                init_image=None if init_image is None else Image.open(init_image),
                scheduler=scheduler,
                strength=strength,
                num_inference_steps=num_infer_steps,
                guidance_scale=guidance_scale,
                eta=0.0,
                create_gif=bool(create_gif),
                model=model,
                callback=progress_callback,
                callback_userdata=conn
            )

        end_time = time.time()
        print("Image generated from Stable-Diffusion in ", end_time - start_time, " seconds.")
        image = "sd_cache.png"

        if ("controlnet" in model_name) and "referenceonly" not in model_name:
            output.save(os.path.join(weight_path, "..", image))
            src_width, src_height = output.size
        elif("inpainting" in model_name or model_name == "sd_1.5_square_lcm" or "sd_3" in model_name or "sdxl" in model_name):
            output.save(os.path.join(weight_path, "..", image))
            src_width, src_height = output.size          
        else:
            cv2.imwrite(os.path.join(weight_path, "..", image), output)
            src_height, src_width, _ = output.shape

        options.set("model_name", model_name)
        options.set("src_height",src_height)
        options.set("src_width", src_width)
        options.set("inference_status", "success")
        options.save()

        # Remove old temporary error files that were saved
        my_dir = os.path.join(weight_path, "..")
        for f_name in os.listdir(my_dir):
            if f_name.startswith("error_log"):
                os.remove(os.path.join(my_dir, f_name))

    except Exception as error:
        options.set("inference_status","failed")
        options.save()
        with open(os.path.join(weight_path, "..", "error_log.txt"), "w") as file:
            traceback.print_exception("DEBUG THE ERROR", file=file)

    conn.sendall(b"done")

def start():
    model_name = sys.argv[1].lower()
    device_list = ast.literal_eval(sys.argv[2])
    power_mode = sys.argv[3]
    run_thread = threading.Thread(target=run, args=(model_name, device_list, power_mode))
    run_thread.start()

    gimp_proc = None
    for proc in psutil.process_iter():
        if "gimp" in proc.name():
            gimp_proc = proc
            break
    
    if gimp_proc:
        psutil.wait_procs([proc])
        print("exiting..!")
        os._exit(0)

    run_thread.join()

if __name__ == "__main__":
   start()
