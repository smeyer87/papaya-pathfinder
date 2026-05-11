# Background
This project is something I cloned from an online repo shared by a public makerspace repo and described in the README.md file.  

I am building the full size (pathfinder) design.
- You may ignore the files in the 'pathfinder-mini' folder.  That is a different project I am not building.
- I don't believe we need the 'android-controller' or 'desktop-controller' folders either as I intend to use a standard R/C controller. See below section.

I have completed the 3D printing and am in the process of setting up the electronics per my custom interpretation of a wiring diagram schematic provided by the project owner.  

# My specific project goals
1. Improve the existing documentation, particularly the README.md file to better reflect the current state of my version of the project and the build process.  
2. Add documentation for the changes I have made to the electronics and software.  
3. Add documentation for any new features I add to the project.  
4. I do not want to contribute back to the online project yet, so I may need to fork (?) this to my own repo for code control for the enhancements I am making?  I'm not clear on how to fork online projects or maintain a copy for my own use.  I believe this is allowed under the Apache 2.0 license (file in the project root).

# Gap analysis
1. I intend to use the firmware-elrs section of the repository but I have never done an RC project before so I'm unclear exactly how to wire up the antenna / receiver with the ESP32 component.  
2. I have a RadioMaster ELRS-RP3-V2 receiver for the ELRS component.  I need to know how to wire this into the ESP32 as the project owner did not specify how to add this.  (red, black, green, white wire connections - where to connect each to the ESP32.)
    a. I'm not sure if you can read the 'Papaya Wiring Layout.xlsx' file but this has the wiring connections in progress.
    b. On the ESP32, the following pins have already been assigned: 
        - Pin 7: Servo #2 white
        - Pin 10: BTS #2 - pin 1
        - Pin 11: BTS #2 - pin 2
        - Pin 12: BTS #1 - pin 1
        - Pin 13: BTS #1 - pin 2
        - pin 38: Servo #4 white
        - pin 41: Servo #3 white
        - pin 42: Servo #1 white
        - 5V IN
        - Ground (by 5V IN)
        - Ground (by TX)
3. I have a BETAFPV LiteRadio 2 SE Radio Transmitter, ELRS V3 2.4 GHz model for the controller.  I need to know how to bind this to the receiver and how to configure the firmware given with the ./firmware-elrs/firmware-elrs.ino file to work with this transmitter.