
What if we could take an existing video
0:02
and then swap the character out with a
0:04
new character using a reference image?
0:07
Well, that's exactly what this new AI
0:10
called Mocha does. This is a free and
0:12
open-source AI tool by this orange team.
0:15
And this allows you to replace any
0:17
character in an existing video just with
0:20
a reference image of your new character.
0:22
And as you can see here, it's able to
0:25
match all the movements of your original
0:28
character, including hand gestures and
0:30
facial expressions and lip movements.
0:33
Plus, it's also able to match the white
0:35
balance and colors of the original
0:37
video. So, your new character will blend
0:39
in seamlessly. Here's another really
0:42
cool example for your reference. Notice
0:44
that the subtitles remain unchanged in
0:47
this video. So, it knows to only segment
0:49
out and replace the original character
0:51
and keep the rest of the video the same.
0:54
Now, a few weeks ago, I featured another
0:56
really similar tool called Juan Animate,
0:58
which also allows you to replace a
1:01
character in a video with a new
1:03
character. In fact, if you want to learn
1:05
more about Juan Animate, see this video
1:07
for a full installation tutorial. This
1:10
is also super useful. But anyways, back
Mocha vs WanAnimate
1:12
to Mocha. They claim that this is even
1:14
better than one animate, especially in
1:17
preserving the colors of the original
1:19
scene so that your character blends in
1:21
more seamlessly. So, as you can see from
1:23
this Spider-Man example, the white
1:25
balance of both Clling and Juan Animate
1:28
are not generated as well as Mocha.
1:31
Here's another example where it's a
1:32
really tricky scene and the light bulb
1:34
is moving in all directions. As you can
1:36
see, in terms of seamlessly inserting
1:39
this character to blend in with the
1:41
original background, it seems like Mocha
1:44
does a better job than one Animate or
1:46
Cling. Here's another example for your
1:49
reference. As you can see, Mocha just
1:51
handles the white balance a bit better
1:53
than the other competitors. Mocha is
1:55
also much better at handling these
1:58
uncommonl looking characters. So for
1:59
example, if we have this character with
2:02
a mask, notice that one animate is not
2:05
actually able to generate this character
2:07
very well. But Mocha is able to insert
2:10
this character very seamlessly while
2:12
retaining all the details in the
2:13
reference photo. Here's another example
2:16
for your reference. And as you can see,
2:18
it's even able to capture talking and
2:21
subtle facial expressions. This is
2:23
definitely one of the best character
2:25
transfer or lip-sync tools that you can
2:27
use right now. Now, here are some of my
Personal demos
2:29
personal demos as well. By the way,
2:31
here's what the interface looks like.
2:33
And don't worry, I'll go over how
2:34
exactly to install and use this in the
2:37
latter half of this video. Anyways, for
2:39
my input video, I'm going to use this.
2:43
And for my reference character,
2:44
actually, let me try to turn the dude
2:47
into this 3D Pixar character. All right.
2:50
And here's what I got. Let me just
2:53
expand this video for you. And as you
2:55
can see, this does the character swap
2:57
really well. It's able to completely
3:00
transfer over his lip movements and his
3:02
hand gestures and his entire body
3:04
movements. Plus, it's even also able to
3:07
get the reflection on the table correct.
3:09
This is an incredibly powerful tool. All
3:12
right. Now, instead of this video, let
3:14
me try another example. This time, I'm
3:16
going to upload this anime video. And
3:19
then, let's swap her out for another
3:21
anime character. I'm going to insert
3:22
this reference character and then press
3:25
run. All right, here's what we get. So,
3:28
let me expand the video for you in full.
3:30
And as you can see, it's also able to
3:32
transfer the new character over pretty
3:35
well. Now, I especially chose this
3:38
character cuz her outfit is super
3:40
complicated. It was able to get her hair
3:43
correct, but the subtle details aren't
3:45
really there. for example, she's missing
3:48
the sleeves on her arms. Plus, the gold
3:50
pin on her head is also not entirely
3:53
correct. So, those were some of my quick
3:55
demos. Next, let's go over how to
3:58
actually install this and use it on your
How to install Mocha
4:00
computer. Now, if you click on this
4:01
GitHub repo on their official project
4:04
page, they do offer some code on how you
4:07
can run this original version on your
4:09
computer, but what we're going to do is
4:11
use CompuI. This is the most popular
4:13
platform for running open-source video,
4:16
image, and audio generators offline. And
4:18
the awesome thing about Comfy UI is you
4:21
can add a ton of plugins to your
4:23
workflow to really optimize the
4:25
efficiency if you have limited compute.
4:27
Plus, it also has automatic offloading.
4:30
So, if the models are not able to
4:32
entirely fit on your VRAM, it's going to
4:34
automatically offload some of that to
4:36
your CPU. So, this video assumes you
4:38
already have Compi installed. If you
4:40
don't definitely see this video where I
4:43
go over step by step how to install and
4:45
use Comfy UI. So anyways, if you scroll
How to install or update WanVideoWrapper
4:47
up here, notice that there's already a
4:49
Comfy UI workflow that incorporates
4:52
Mocha. So let's click on this. And this
4:54
is the one and only Comfy UI W video
4:57
wrapper by this goat called Kiji. Now
5:00
the first step is we need to install
5:02
this Wan Video Wrapper first. So if we
5:04
scroll down a bit, here are all the
5:06
installation instructions. So let's go
5:08
over this really quickly. So first we
5:10
need to go to our Comfy UI folder.
5:13
Notice that I'm using Comfy Windows
5:15
portable which is the recommended
5:16
version. So let's double click on Comfy
5:18
UI and then custom nodes. And then at
5:21
the top here, simply type cmd to open
5:23
this folder up in command prompt. So
5:26
here it says we just need to clone this
5:27
repo into the custom nodes folder. So
5:30
I'm going to scroll up to the top of
5:31
this GitHub repo and then click on this
5:34
green button and then copy this URL. And
5:37
then over here I'm going to write get
5:39
clone and then paste the URL in here.
5:41
Now I already have this. So the message
5:43
that I got is this already exists. Now
5:46
if you're like me and you already have
5:48
this installed but you did this a long
5:51
time ago then it's also worth updating
5:53
this wrapper first. So how you do that
5:55
is first let's exit out of command
5:57
prompt and then in my custom nodes
5:59
folder we need to actually head to this
6:02
one video wrapper. So let's double click
6:04
into this and then again at the top here
6:06
let's type in cmd to open this up in
6:09
command prompt and then afterwards we
6:10
just need to write get pull like this.
6:13
So it's going to proceed to pull all the
6:16
updates that are from the latest version
6:18
on GitHub. Now let's say you're
6:20
installing this fresh for the first
6:22
time. You also need to install the
6:25
dependencies that are listed in this
6:27
requirements.ext file. So in order to do
6:29
that, if you're running the Windows
6:31
portable version, we need to run this
6:34
code. So let's first exit out of this
6:37
command prompt. And then in my Comfy
6:39
folder, notice that this is the root
6:41
folder, which is called by default Comfy
6:44
Windows portable. At the top here, let's
6:46
type in cmd again to open this up in
6:48
command prompt. And then afterwards, all
6:50
we need to do is copy this line and then
6:53
paste it in here. So basically what this
6:55
does is it's going to use Python which
6:58
is located in our Python embedded folder
7:00
and it's going to proceed to download
7:02
all the requirements in the
7:03
requirements.ext file which for your
7:05
reference is over here and here's the
7:07
list of packages that it needs. All
7:09
right so after doing that you should
7:11
have successfully installed or updated
7:14
this one video wrapper. So let's exit
7:16
out of command prompt and we can proceed
7:18
to load up comfy UI. So let me double
7:21
click on this. All right. So after
7:23
starting up Comfy UI, the next step is
7:25
to load the Mocha workflow onto here.
7:28
Now the awesome thing about Comfy UI is
7:30
you don't need to build all these nodes
7:32
and noodles from scratch. You can just
7:34
drag and drop an existing workflow onto
7:36
your interface. So back in this one
7:39
video wrapper GitHub repo, you can see
7:41
that we have this example workflows
7:44
folder over here. So let's click on this
7:46
and then we are going to download this
7:48
one. Mocha replace subject version two.
7:51
So let's click on this and then I'm
7:53
going to click on this button to
7:55
download the JSON file. You can save
7:57
this anywhere you want. I'm just going
7:58
to save it in my comfy UI root folder.
8:00
Now after downloading this, all we need
8:02
to do is drag and drop the JSON file
8:04
onto the Comfy UI interface. And voila,
8:07
here is the entire workflow pre-built
8:10
for you. Now when you drag and drop this
8:13
onto your interface for the first time,
8:15
you might see some nodes that are
8:16
outlined in red, which indicates that
8:18
they are missing. So that means you have
8:21
not updated the latest version of one
8:23
video wrapper. So see my earlier steps
8:25
in this video to make sure you've
8:27
updated one video wrapper.
8:28
Alternatively, you can also click on
8:30
manager and then click on install
8:32
missing custom nodes. And while you're
8:34
at it, it's probably a good idea to
8:36
update Comfy as well. Anyways, at least
8:38
for me, you can see that I don't have
8:40
any missing nodes. Now, before I go over
8:42
this workflow and how it works, we need
8:44
to actually install some additional
Downloading required models
8:47
models for this to actually work. So
8:49
over here, this includes some model
8:51
links. First of all, of course, we need
8:53
to download the Mocha model. Now, back
8:56
to this original project page. If you
8:58
click on the official hugging face repo
9:01
and then you click on files and versions
9:03
and then preview, notice that the
9:05
original Mocha model is like 28 GB in
9:09
size, which certainly does not fit on
9:12
most consumer grade GPUs. Fortunately,
9:14
for this workflow, KI has already
9:17
created a quantized FP8 version, which
9:19
is much smaller. So, let's click on this
9:21
link, which would take us here. And
9:24
notice that this Mocha model is only 14
9:27
GB in size. So, this definitely fits
9:30
within my 16 GB GPU. This might fit on
9:34
even 12 GB of VRAM with some offloading,
9:37
but don't take my word for it. You're
9:38
going to need to try it out yourself.
9:40
So, anyways, let's click download. And
9:43
this goes in comfy UI and then in models
9:46
and then diffusion models. Let's click
9:48
save. All right. Now, after downloading
9:50
the Mocha model, there are also a ton of
9:52
things you need to download from this
9:54
hugging face repo. So, let's click on
9:56
this hugging face repo and then click on
9:58
files in versions. And you should see a
10:01
huge list of files, which is kind of a
10:03
mess. But here's what you need to
10:05
download. First of all, going back to
10:07
this workflow, if we scroll all the way
10:10
over here, notice that this requires the
10:13
one 2.1 VAE. This is basically in charge
10:16
of encoding and decoding your video. So,
10:19
going back to this massive list, I'm
10:21
just going to press Ctrl+F and search
10:23
for VAE. And here is what we need to
10:26
download. Now, there are two different
10:28
VAE versions. Of course, I'm going to
10:30
download the BF-16 one, which is a bit
10:32
smaller and more optimized for a lower
10:34
VRAM. Also make sure you download this 1
10:37
2.1 VAE and not the one 2.2 version.
10:40
Anyways, for this I'm going to click
10:42
download over here and this goes in
10:44
comfy UI and then in models and then
10:47
VAE. In addition to this VAE, we also
10:50
need to download this text encoder. So
10:53
going back to this huge list, let's
10:54
press Ctrl+ F again and search for UMT.
10:57
So notice that down here there are two
11:00
text encoders you can download. There's
11:01
going to be a BF-16 version which is 11
11:04
GB in size and then the smaller FP8
11:07
version which is like half the size. So
11:09
again for me since I don't have a lot of
11:11
VRAM I'm going to download the smaller
11:14
FP8 version. So let me click on this and
11:17
this goes in Comfy UI in models and then
11:20
in text encoders. Now this workflow uses
11:23
one more optional model which is this
11:26
light X2V model. What this basically
11:29
does is it helps accelerate your
11:31
generation by like many times. Usually
11:34
for a one video, it requires like 20 to
11:37
30 steps to generate the damn video, but
11:39
with this light X2V model, you can
11:42
reduce it down to six steps. So, this
11:44
basically speeds up your generation by
11:46
like four to five times. If you don't
11:48
want to download this, you could select
11:49
this node and then press Ctrl +B to
11:52
disable or bypass it. But it's highly
11:54
recommended that you actually install
11:56
and use this Light X2V model. Otherwise,
11:58
it's going to take an eternity for you
12:00
to generate a video. All right, so going
12:02
back to this massive list of files to
12:05
download Light X2V, simply look for this
12:08
Light X2V folder. So, I'm going to click
12:10
into this. And again, here it has a ton
12:13
of models for you to choose from. So we
12:16
need to choose basically the text to
12:18
video models. So one of these ones and
12:21
here notice that basically these models
12:24
have different ranks. The higher the
12:26
rank the higher quality the model is but
12:28
also the larger the model is. So for
12:30
example rank 256 would be 2.5 GB whereas
12:34
rank 4 would be only 46 mgby. So it
12:38
really depends on how much VRAM you have
12:40
or how much quality you want. For me,
12:43
I'm going to download this rank 32 one,
12:46
which is only 300 megabytes in size. So,
12:49
I'm going to click download. And this
12:51
goes in Comfy UI in models and then in
12:54
Lauras. All right. After downloading all
How to use Mocha workflow
12:57
those models, we can now get started
12:59
with the workflow. So, the first thing
13:01
you need to do is actually press R to
13:05
refresh your models list. So, it will
13:07
show up when we select the models. Now,
13:09
this is quite a huge and messy workflow.
13:11
So let's zoom in on this section first
13:14
to select all the models that we just
13:16
downloaded. So over here, here is where
13:18
we load the main Mocha models. So let's
13:21
click on this dropown and select this
13:23
one. All right. And then over here,
13:26
again, this is optional but highly
13:27
recommended. Let's click on this
13:29
dropdown and select light XTV text to
13:32
video. And then over here for this VAE
13:36
component, we need to click on the
13:37
dropown and select one 2.1 VAE. And then
13:40
over here for this text encoder, I'm
13:43
going to select this FP8 version. All
13:46
right, that's pretty much it. Now, what
13:48
I'm going to do first is actually hold
13:50
control and drag over all these nodes to
13:53
select them. And then either press this
13:55
button here or Ctrl +B to basically
13:59
disable or bypass these nodes because
14:01
the first step is we need to upload the
14:03
video and create a mask or basically a
14:06
segmentation map of the video first. Let
14:08
me show you exactly what I mean by that.
14:10
So over here is where you would upload
14:13
your video. So let me upload this video.
14:16
And there's only one setting that you
14:17
really need to note here, which is this
14:19
frame load cap. This is basically how
14:22
many frames of the video you want to
14:23
keep. So assuming this is 24 frames per
14:26
second. 81 / 24 frames per second is
14:29
roughly like 3 seconds. So, if your
14:32
video is longer than 3 seconds and you
14:34
set this to 81, it's going to cut your
14:36
video at the 3se secondond mark. If you
14:38
want it to actually use your entire
14:41
video, then you should set this value to
14:42
zero. By the way, if you're not sure
14:44
about what any of these settings mean,
14:46
you can also click on this question mark
14:49
thing over here, which explains all the
14:51
settings. So, here, if I scroll down a
14:54
bit here, you can see what this frame
14:57
load cap means. So if I set this to
14:59
zero, then all the frames are loaded.
15:01
All right. So that's the first step. The
15:02
second step is to upload your reference
15:05
character which you want to insert. So
15:08
let's try this one. Now here's the thing
15:10
here. It says we recommend using a
15:13
reference image with a clean background.
15:15
So what you should do is like use Nano
15:18
Panana or an image editor to remove the
15:21
background of your photo first before
15:23
uploading it into here. That's actually
15:25
what they recommend. But at least for
15:27
me, I uploaded a ton of reference photos
15:29
with backgrounds and that didn't really
15:31
seem to affect the video. So, I just
15:33
skipped this step. But if you do see
15:34
like some background artifacts in your
15:36
final video, then it's recommended that
15:38
you upload a character with a clean
15:40
background instead. So, that's ref one.
15:43
But, as you can see here, there's an
15:45
optional ref 2 component, which is
15:48
disabled by default. But here, you can
15:50
upload an additional image of your
15:53
reference character. And here it says
15:56
that it's best to use a face image for
15:58
ref 2 to enhance face fidelity. So
16:01
basically for ref one, this is
16:03
mandatory. This is for like a midshot or
16:06
full body shot of your character. And
16:08
then for ref 2, this is optional, but if
16:10
you want to transfer the facial details
16:12
even better, then you should upload a
16:14
face photo of your character. For me,
16:16
I'm just going to leave this off. All
16:18
right, so that's pretty much it. And
16:19
basically the video goes through this
16:22
segmentation step. So, let me press run
16:24
first to show you what happens. All
16:26
right. So, here's why I bypass these
16:28
nodes and only run these nodes first.
16:31
So, basically, what you need to do is
16:34
actually drag the green dots plus the
16:37
red dots on your image so that it would
16:39
correctly segment the character in your
16:42
image. So, right now, as you can see,
16:44
it's also capturing some of the mic,
16:46
which is not ideal. So the red dot
16:49
should actually be on the mic so it
16:51
knows to segment out this mic. And let's
16:55
add the green dots here and here for
16:57
example and see what happens.
17:01
All right. So now if I do that then it's
17:03
not capturing her hair. So let me also
17:06
move the green dot up here a bit and the
17:09
red dot over here a bit because part of
17:11
her top is also not captured. And then
17:14
let's press run again. And it's still
17:16
not really correct. I'm intentionally
17:18
showing you this example because the
17:20
segmentation is a bit trickier. So next,
17:22
let's place the green dot like on her
17:24
headphones. So it also removes her
17:26
headphones as well. And let's see if
17:28
this is any better. All right. So this
17:30
looks a lot better. I think this mask is
17:32
good enough. And that's pretty much it.
17:34
Once you're satisfied with the mask,
17:36
then we can now press Ctrl and select
17:39
all these nodes and press Ctrl +B to
17:42
enable them again. All right. So
17:44
basically your video and your your
17:47
reference character image is going to be
17:49
passed through this Mocha model. Now
17:52
here this one video wrapper workflow
17:54
usually contains this torch compile
17:57
settings. Now this torch compile
17:59
settings often creates a ton of problems
18:01
from users because here it says it does
18:03
require you to have Triton installed
18:05
which is a pain to install for Windows
18:07
plus you need to 2.7 or higher. Now at
18:10
least for me I don't have Torch 2.7 or
18:12
higher. So what I like to do is just
18:14
take this component and disable it by
18:17
pressing this button or controlB. So
18:19
this is an optional component. All
18:21
right. So it's using the mocha model
18:23
plus you can also add this light XTV
18:26
lower to speed up your generation by
18:28
like four to five times. And then next
18:30
it's going through this block swap
18:32
component. And this component if you
18:35
hover over this question mark basically
18:37
swaps some of your VRAMm usage to your
18:39
CPU memory. And this is especially
18:41
useful if you have low VRAM. Here it
18:44
says that Mocha is actually a lot
18:45
heavier on VRAM than other models. So
18:48
lots of block swap is probably
18:49
necessary. So the default for 14 billion
18:52
parameter models is 40. If you still get
18:55
an out of memory error, then I would try
18:57
to increase this to like 50 or 60 and
19:00
see if that works. And then here you
19:02
have the option of entering a positive
19:04
prompt and negative prompt. But
19:06
honestly, you don't really need to enter
19:07
anything because it's just replacing the
19:09
character of an existing video. So, we
19:12
don't have to really worry about that
19:13
there. All right. Then, basically, this
19:16
part takes your input video from over
19:18
here. And then the mask from over here.
19:20
So, this tells it, you know, what part
19:23
to remove from the video and what parts
19:25
to keep and then the reference image
19:28
which we uploaded over here. And then
19:30
all these inputs basically go through
19:32
this K sampler to generate the video.
19:35
Now, here is the step count. This is
19:37
basically how many steps it takes for
19:39
the model to generate your video. In
19:41
general, the more steps you have, the
19:43
higher the quality would be, but it's
19:45
going to take slower. However, note that
19:47
because we are using this light X2V
19:50
Laura, it's recommended to keep the step
19:52
count to four to six only. And then same
19:55
with CFG, it's recommended to just keep
19:57
this at one. Here for theuler, this is
20:00
basically the algorithm that is used to
20:02
generate the video. Feel free to play
20:03
around with these settings, but the
20:05
default value seems to work pretty well
20:07
already. And that's pretty much it. You
20:09
don't really need to worry about all of
20:10
these settings. All right, so let's
20:12
press run and see what we get. All
20:14
right, now you can see it's being fed
20:17
through this case sampler to actually
20:19
generate the video and then it's being
20:21
decoded. And here's what we get. So, it
20:23
does the character transfer very well
20:25
while keeping the details of the mic
20:28
intact. Very cool. Notice it's able to
20:30
handle facial expressions very well,
20:33
especially her eye movements, which on
20:35
animate doesn't really do well. Now, by
20:37
default, the save output setting is set
20:40
to true. So, this is going to be
20:42
automatically saved in your company UI
20:44
output folder. One other thing to note
20:46
is that by default, your video format is
20:49
going to be like this, where on the left
20:51
is your original video and on the right
20:53
is your generation. What if you want to
20:55
only output your generation as a
20:58
separate video? Well, to do that, what
21:00
we need to do is actually instead of
21:02
using this concatenate step, we just
21:04
need to directly link this images output
21:07
from this decoder to this images input.
21:10
So this basically removes this step. So
21:14
now if I press run again, it should only
21:16
output my generation and not the
21:19
original video side by side. So in a
21:21
nutshell, that is how to run Mocha
21:23
locally on your computer. This might
21:25
look like a super complicated workflow
21:27
to you at first, but I hope that this
21:30
tutorial makes it a lot easier for you
21:32
to understand. This is probably the best
21:35
character replacement that we have right
21:38
now. And this unlocks a ton of
21:40
possibilities. Like, you can just film
21:41
yourself or someone else acting out a
21:43
scene and then replace them with your
21:46
new character and create an entire film
21:48
from that. or you can also replace
21:50
people in existing videos to generate
21:52
some really funny or viral content.
21:55
Anyways, let me know what you think of
21:56
Mocha. And if you run into any errors
21:59
during the installation, welcome to
22:01
paste the error message in the comments
22:03
below and I'll try to help you
22:04
troubleshoot as much as possible. As
22:06
always, I will be on the lookout for the
22:09
top AI news and tools to share with you.
22:12
So, if you enjoyed this video, remember
22:14
to like, share, subscribe, and stay
22:16
tuned for more content. Also, there's
22:18
just so much happening in the world of
22:20
AI every week. I can't possibly cover
22:22
everything on my YouTube channel. So, to
22:25
really stay up to date with all that's
22:27
going on in AI, be sure to subscribe to
22:30
my free weekly newsletter. The link to
22:32
that will be in the description below.
22:34
Thanks for watching and I'll see you in
22:36
the next one.
