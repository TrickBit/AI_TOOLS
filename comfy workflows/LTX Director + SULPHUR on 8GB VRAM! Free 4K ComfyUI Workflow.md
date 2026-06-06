# LTX Director + SULPHUR on 8GB VRAM! Free 4K ComfyUI Workflow


###### 20,012 views  Jun 1, 2026  #comfyui #localai #rtx5060

* DOWNLOAD the 8GB VRAM optimized LTX Director ComfyUI Workflow: https://drive.google.com/file/d/1Zy2m...
* RTX Super Resolution Upscaling Workflow: https://drive.google.com/file/d/1g3fI...
* Hunyuan-Foley Workflow: https://drive.google.com/file/d/16BhM...
* Free & Unlimited Images (GenTube App): https://www.gentube.app/p/prompt-nerd...
* The 3-Hour AI Short Film Workflow: https://www.topview.ai/?via=tensor

Master local AI video generation with the newly released LTX Director node and the highly optimized Sulphur model inside ComfyUI. This comprehensive walkthrough covers a complete, low-VRAM friendly local workflow capable of generating high-fidelity text-to-video and image-to-video sequences without relying on expensive cloud platforms. 

We break down the exact node configurations and architectural optimizations required to run these advanced video generation models smoothly on low-VRAM hardware with just 8GB of VRAM like the NVIDIA RTX 5060. Learn how native FP8 processing, Sage Attention layers, and chunk feed-forward structures maximize generation speeds, maintain system stability, and completely eliminate out-of-memory errors on consumer-grade setups.

## 🛠️ What This Workflow Achieves

* Complete Timeline Control: Utilize multi-prompt block structuring to guide specific narrative beats and cinematic transitions frame-by-frame. 
* 
* Advanced Multi-Image Inferences: Feed multiple reference images into the model pipeline to maintain structural character and environmental consistency.  
* 
* 8GB VRAM Optimization: Learn the exact resolution thresholds (1080p, 1600 x 900, and 720p) to safely push maximum video durations locally.  
* 
* Single-Pass Rendering: Bypass secondary artifact generation issues while drastically reducing processing overhead.  
* 
* Local Sound Design Integration: Incorporate open-source audio architectures like Hunyuan-Foley to build complete cinematic compositions entirely on your own rig.

## ⏱️ Video Timestamps

* 0:00 - Short Video preview (Director Node Creation)
* 0:31 - LTX Director Node Intro
* 0:45 - Image to Video
* 1:20 - Text to Video
* 2:35 - Support the Creator
* 2:40 - Free & Unlimited mobile-first image creation
* 3:45 - LTX Director Node Requirements
* 4:32 - FP8s or GGUFs? (Sage Attention)
* 6:19 - Sulphur vs LTX 2.3 Distilled 1.1
* 6:35 - LoRAs & Download Links
* 6:52 - 8GB Optimized LTX Director Workflow
* 7:25 - Mastering the LTX Director Node
* 10:05 - Limitations
* 10:35 - Generating High octane action scenes
* 10:58 - Local vs Cloud breakdown: The reality

## 💻 My Setup :

* Laptop: Gigabyte A16
* GPU: RTX 5060 (8GB VRAM)
* RAM: DDR5 32GB (Dual Channel)

💼 Business Inquiries & Sponsorships

###### #comfyui #aivideo #localai #generativeai #machinelearning #ltxdirector #sulphurmodel #rtx5060 #openaivideo #gpuoptimization**

📥 More Workflow videos: https://www.patreon.com/cw/TensorAlchemist 
💬 Free Workflow Help & Discord https://discord.com/invite/NyAWaxfSVN

The 3-Hour Seedance 2.0 Short Film Workflow: What We Local LTX 2.3 Users Are Missing!
by Tensor Alchemist : https://www.youtube.com/watch?v=a6Avzw-m7gA


### Transcript
### LTX Director Node Intro
0:31 - The LTX Director node is finally here,  
0:33 - and it makes things a whole  lot easier for the casual user. 
0:36 - This is an all-in-one workflow where  you can generate text-to-video,  
0:39 - image-to-video with multiple reference images,  lip-sync, or even create an entire short movie. 
##### Image to Video
0:45 - Let's check out some  image-to-video generations first. 
1:17 - Now, check out these text-to-video generations. 
##### Text to Video
2:31 - As you can see, this is an absolute  powerhouse of a workflow. Here is a  
2:35 - quick note from the creator—massive shoutout to  him, and make sure to go show him some support. 
##### Free & Unlimited mobile-first image creation
2:40 - Now, before we dive deeper into the workflow, let  me show you a free, unlimited, mobile-first tool  
2:45 = where you can create art and play with prompts  wherever you are. This is GenTube. It's a fun,  
2:49 - endless way to experiment with AI art without  needing to spin up ComfyUI when you're away from  
2:54 - your rig. You can go crazy testing out prompts  while you're literally just waiting for the bus.  
2:55 - On GenTube, you're never starting from scratch;  there's always a cool starting point waiting for  
3:00 - you. Plus, there's a thriving community constantly  dropping new ideas and inspiration through remixes  
3:05 - and feeds. Best of all? It's completely  free, instantaneous, and has zero limits. 
3:10 - You just type whatever pops into your head, and it  shows up in like a second. If you don't love it,  
3:15 - hit it again. And again. Since  there's no cost, you can afford to  
3:18 - be incredibly picky. It's absolutely perfect for  us ComfyUI lovers who just want to quickly test  
3:19 - ideas without firing up the whole setup. When you finally hit on one you like,  
3:21 - you can easily edit it. Change a detail,  add an element, or take something out  
3:25 - entirely. That's the part where the artwork  actually starts feeling like it's yours. 
3:26 - Then there's the swipe feature. Same core idea,  just different versions. You can tweak the mood,  
3:30 - lighting, and overall vibe. You might think  you know exactly what you want, but then you  
3:32 - swipe and go, "Oh, wait, actually... that one." All your creations live right on your profile.  
3:34 - After a few weeks, it organically turns  into your own personal little gallery,  
3:38 - which is honestly the best part. And that's  
3:40 - it—it is flat-out the easiest way to experiment  and make cool stuff on the go. You never have to  
3:41 - break your creative flow just because you stepped  away from your ComfyUI machine. Open it up,  
3:42 - and you're creating within the first 20 seconds. Now, this next part is crucial. Make sure you're  
##### LTX Director Node Requirements
3:46 - fully up-to-date and running the nightly  version. Also, update all your nodes by  
3:50 - clicking the 'Update All' option right here.  Fair warning: this will take some time. Do  
3:55 - not panic if it takes longer than 10 minutes, and  whatever you do, don't cancel the process halfway  
4:00 - through. I've included the exact environment  I used to generate these clips, so keep in  
4:04 - mind you might get slightly different results  or errors depending on your specific setup. 
4:08 - You don't necessarily have to use the very  latest CUDA version. Just stick with the  
4:12 - one that plays nicely with your specific GPU. Now, I haven't installed the absolute latest  
4:17 - NVIDIA driver just yet, but the good news  is right here: ComfyUI recently released 
4:21 - an update to improve model loading and offload  times. This drastically boosts performance for  
4:26 - heavier workflows like LTX video generation, and  I am seriously looking forward to testing it out. 
4:31 - FP8s natively support Ada Lovelace and Blackwell  GPUs, and Sage Attention natively supports FP8s.  
##### FP8s or GGUFs? (Sage Attention)
4:38 - Combining them is like pouring California  rocket fuel into your rig—it significantly  
4:43 - educes both your memory footprint  and your overall generation times. 
4:47 - Now, don't get me wrong here—and by the way,  huge thanks for your feedback in the comments;  
4:50 - it really helps me understand the bottlenecks  you guys are facing and improves these videos.  
4:54 - Let me clear this up without any confusion: I'm  not saying you can't use FP8s on Ampere, Turing,  
4:59 - or Pascal GPUs. The keyword here is "native  support." Because FP8s natively support Ada  
5:05 - Lovelace and Blackwell, even low-VRAM users  like me running an RTX 5060 can handle larger  
5:11 - FP8 models without constantly worrying about  brutal SSD offloading during the sampling process. 
5:17 - But, if you're rocking a beefier card  like an RTX 3090 with 24 gigs of VRAM,  
5:23 - you can easily brute-force the FP8s, or even  the BF16s, as long as you have enough system  
5:28 - RAM. You won't have to stress about SSD offloading  at all. They work absolutely fine, and on top  
5:29 - of that, you can still enable Sage Attention. However, if you're stuck on 8 or 12 gigs of VRAM  
5:34 - using Ampere, Turing, or Pascal architecture,  and you've got 32 gigs of system RAM or less,  
5:40 - GGUFs are going to give you the best stability  and the essential breathing room your PC needs.  
5:45 - As a few of you eagle-eyed viewers pointed  out, the Q5 K_M is only 16 gigs, and honestly,  
5:51 - there's barely a noticeable drop in quality  compared to the massive 24-gig FP8 version. 
5:56 - Plus, the 18-gig Q6 version  can sometimes actually spit out  
5:59 - higher-quality results than the standard FP8. Keep in mind, though, Sage Attention doesn't  
6:05 - natively support GGUFs—unless one of you wizards  down in the comments knows about a patch I missed. 
6:10 - So, at the end of the day, whether you  use GGUFs or FP8s depends entirely on  
6:15 - your system specs and personal preference. Moving on to the models, I used the Sulphur  
##### Sulphur vs LTX 2.3 Distilled 1.1
6:20 - FP8 version and the Distilled 1.1 for these  generations. Sulphur definitely performs  
6:26 = better overall, but fair warning: because it's so  heavily fine-tuned, it might occasionally throw  
6:33 - some unexpected surprises your way. And right here, you'll find  
##### LoRAs & Download Links
6:36 - the links to all the models. I've also included the links to  
6:39 - the LoRAs I used for a few of my generations.  Just remember, only bake in LoRAs if they're  
6:44 - actually necessary for your shot. You can grab the official workflow by  
6:48 - heading over to 'Templates' right here and  typing "LTX Director" into the search bar. 
##### 8GB Optimized LTX Director Workflow
6:53 - This is the official workflow, and as you can  clearly see, it's significantly different from  
6:58 - the optimized version I use for my own  generations. I've deliberately added our  
7:02 - familiar model nodes and the 'Chunk Feed Forward'  node to give us 8GB VRAM users a fighting chance. 
7:08 - The second noticeable difference is  that I stripped out the second pass  
7:12 - and kept only a single pass for my renders. This was mainly because I kept running 
7:16 - into this weird artifacting issue at  the very end of my clips when using  
7:20 - multiple reference images. Removing that  second pass completely solved the problem. 
7:24 - Let's break down the different ways  you can use the 'LTX Director' node. 
##### Mastering the LTX Director Node
7:28 - If you're strictly doing text-to-video  generations, just hit the 'Add Text' option 
7:33 - here and stretch it out to match the length of  your clip. Alternatively, you can click this  
7:37 - 'plus' icon and select the text segment option. Now, the absolute best part of the Director  
7:43 - Node is the sheer precision it gives  you over your text-to-video prompts.  
7:47 - If you want granular control, you can stack  multiple text blocks instead of just relying  
7:51 - on a single prompt, as you can see here. I generated this exact clip by layering  
7:56 - multiple text blocks into the prompt timeline. If you're trying to push 1080p clips out of an  
8:01 - 8GB VRAM card, do yourself a favor and  cap the length at a maximum of 8 seconds  
8:05 - to avoid those dreaded 'out of memory' errors. If you need to stretch it to 10 or 12 seconds,  
8:10 - drop your resolution down to 1600 by 900. If  you're aiming for anything longer than that,  
8:15 - you'll need to drop down to 720p. When you transition to image-to-video generations,  
8:19 - you simply upload your base image, type your  prompt right here, and then drop in additional  
8:24 - text blocks to guide the motion. You even have the  flexibility to load up multiple reference images. 
8:29 - I relied on the Linear Quadratic scheduler for  these specific generations, but you can definitely  
8:34 - get away with using the 'Simple' scheduler, too. As for samplers, I bounced between 'Euler  
8:38 - Ancestral' and 'LCM,' depending entirely  on the context of the shot. If you're after  
8:43 - highly stable results with decent lip-sync,  Euler Ancestral definitely has the edge.  
8:48 - But for prompts demanding a lot of dynamic  movement, LCM gave me much better results. 
8:53 - These are the exact settings I dialed in to  generate the opening clip of my short video.  
8:57 - Once you insert your target frame rate  and specify the duration in seconds,  
9:01 - the total frame count locks in automatically,  so you don't even have to touch it. 
9:05 - Now, this is where you truly start to see the  magic of the Director Node. As you can see,  
9:10 - I used it to meticulously craft the exact shot I  envisioned. I started with this full moon image,  
9:15 - and immediately after, for a precise  one-second window, I fed it instructions to  
9:19 - transition smoothly into this over-the-shoulder  tracking shot of a man driving a horse-drawn  
9:24 - carriage. I actually didn't even use the  transition LoRA here, though occasionally,  
9:28 - it might give you a slightly cleaner result. Next, I queued up a two-second text prompt to  
9:33 - introduce the following scene, and finally,  I dropped in a third image alongside text to  
9:38 - anchor the final sequence. You can absolutely  use that third image as your hard end frame,  
9:43 - or keep layering in more reference images to  see what works best for your specific vision. 
9:47 - I did have to run Hunyuan-Foley for the background  sound design, because the base model spit out some  
9:52 - seriously ridiculous music. Don't worry, I'll  attach the link for that workflow down below with  
9:56 - the rest. For the finishing touches, I used Google  AI Studio to generate the voiceover and stitched  
10:02 - all the clips together in DaVinci Resolve. Now, as amazing and flawless as the Director  
##### Limitations
10:07 - Node feels to use, it doesn't magically fix  the inherent flaws of the underlying model.  
10:12 - New fine-tunes like Sulphur have definitely  patched up some weak spots, but honestly,  
10:17 - the base model is still highly unstable, and  the learning curve remains incredibly steep. 
10:21 - It still struggles hard with fast-paced,  high-octane action scenes. You're going  
10:26 - to see a lot of ugly morphing—especially in wide  shots or anything that isn't a tight close-up—and  
10:31 - realistically, you'll end up rerolling multiple  generations just to nail one decent take. 
##### Generating High octane action scenes
10:36 - If your goal is to crank out a short film filled  with blockbuster action and production-level  
10:40 - consistency in just a few hours, you still  need to lean on cloud models. For context,  
10:45 - it took me just 3 hours from start to finish  to create this short movie—and that includes  
10:50 - writing the script, building characters, and  generating highly consistent footage. I'll drop  
10:55 - the link to that one in the pinned comment. As you just saw, though, the Director Node  
##### Local vs Cloud breakdown: The reality
10:59 - is a massive leap forward for the local scene.  So once again, a huge shoutout to the creator.  
11:04 - Please go show him your support so we  keep getting these incredible tools. 
11:08 - It's true that we still have to rely on the  cloud for those top-tier, flawless results.  
11:12 - But here's the secret: if you take the  time to master open-source models like LTX,  
11:17 - you will save an absolute fortune in cloud  credits. You'll never have to pay to upscale  
11:21 - or interpolate frames again. You can also farm out  all your background scenes—like this one—to LTX,  
11:27 - even if it takes a few tries to get right.  By mastering the open-source side and using  
11:31 - a smart hybrid approach—only paying the  cloud for what's impossible locally—creating  
11:36 - high-quality content without draining your  bank account suddenly becomes a reality. 
11:41 - Let's not forget the most important advantage:  LTX is completely unfiltered. It doesn't put  
11:46 - handcuffs on your creativity in any way. Combine  that freedom with massive community support, and  
11:51 - you get incredible fine-tunes like Sulphur, and  revolutionary tools like the Director Node itself. 
11:57 - At the end of the day, if you  master open-source models like LTX,  
12:01 - you essentially gain the power to batch-generate  an unlimited number of clips completely for free,  
12:06 - while you're literally fast asleep. Your support means absolutely everything  
12:10 - to me. It's what allows me to grow this  channel and keep delivering these free,  
12:14 - low-VRAM-optimized workflows and guides to  you guys. If you found this tutorial helpful,  
12:19 - smash that subscribe button, leave a thumbs  up, and drop your thoughts in the comments

📂Free & Unlimited Images (GenTube App): https://www.gentube.app/p/prompt-nerd?_cid=tensor
📂 The 3-Hour AI Short Film Workflow: https://www.topview.ai/?via=tensor
📂 DOWNLOAD the 8GB VRAM optimized LTX Director ComfyUI Workflow: https://drive.google.com/file/d/1Zy2mjCSOUHJxJrsaVa6Q7VASDQ0A8ZHm/view?usp=drive_link

📂 RTX Super Resolution Upscaling Workflow: https://drive.google.com/file/d/1g3fIMMhZEWViafnKgCBPcrAyQMU8MwQL/view?usp=drive_link

📂 Hunyuan-Foley Workflow: https://drive.google.com/file/d/16BhMqagD3pEhcj8nHCw73tXxgZx8AS5O/view?usp=drive_link

Need help with THIS SPECIFIC workflow? If you run into any errors, head over to the 'Workflow Help' section on my Discord: https://discord.gg/NyAWaxfSVN. It’s completely free! Please note that I can only provide troubleshooting for the workflows featured in my videos.

##### Comments

Hey brother! I have been using text to video workflow quite a bit. everytime when I generate a video, it writes around 8-10 gb on my SSD. I have 48GB ram and 8GB 5060. I tried decreasing the resolution, length or even further optimizing the workflow, but everytime the result was exactly same, even with reduced resolution and duration; the SSD offloading was around 10gb per video. On additional research, it was found that under Upscale Sampling 2x, sampler custom advance was the main culprit and the second was the VAE Decode titled. I tried everything, if all failed. Could you please optimize the workflow for my system? I also tried switching fp8 model with Q5 KM varient, but it also used my SSD around 10gb per video.  The 10 gb writes are done within couple of seconds, other than that the model heavily usages my RAM. Could please you help me with it?

=========================================================================================

@Alex-M_Live
	Can I ask a question? For some reason, all my videos turn out in slow motion. How can I remove this effect? For example, if a woman is walking down the street or running along the beach, all the movements look like they're in slow motion.
@TensorAlchemist 
	Hi! Experiment with different samplers like 'euler', 'euler_ancestral', or LCM. The most important thing, of course, is still your prompt. Make sure to pair the sampler change with clear action words.

=========================================================================================

@SpideyKish
	how to fix slow motion ?
@victormurori4367
	maybe write 60fps on the prompt, ltx 2.3 is like grok imagine with the slow motion issue 

=========================================================================================
@Alex-M_Live
	Can I ask a question? For some reason, all my videos turn out in slow motion. How can I remove this effect? For example, if a woman is walking down the street or running along the beach, all the movements look like they're in slow motion.
@TensorAlchemist
	Hi! Experiment with different samplers like 'euler', 'euler_ancestral', or LCM. The most important thing, of course, is still your prompt. Make sure to pair the sampler change with clear action words. 

=========================================================================================

@echovaleys
	Hi, does it take longer with one pass or two passes? Why does the resolution then reset with two passes in between because you chose one pass with only full resolution?
@TensorAlchemist 
	One pass can be faster because it cuts out extra model loading and offloading cycles between samplers. To answer your question about the resolution shift: when I removed the second pass, I manually changed the Scale value from 0.50 to 1.0 so the workflow would generate at full resolution right from the start.
@echovaleys 
	​​ @TensorAlchemist Thanks, So with just one pass there are no more artifacts than with two passes where the video is upscaled? And  wanted to ask you if it is possible to make a mix of custom audio + audio prompt ltx to have two audio outputs from the director node 
	
=========================================================================================

@beserklee290   
	i also have Rtx 3060 12gb and 48gb of system ram, which distilled model should i download ?
@princemalviyaPM  
	Any fp8 should be fine 
	
=========================================================================================

@SpideyKish
	it has face consistency like wan 2.2 ?
@TensorAlchemist
	With this node and workflow, so far I've gotten facial consistency similar to WAN 2.2, even when using a single reference image.
	
=========================================================================================

@whatif7696
	Will it work on 4080 12gb 32GB System RAM
@TensorAlchemist
	You're good to go.
	
	

