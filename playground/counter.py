import os
# set up  a new variable integer with initial 0
words = 0
# set up a new bool variable called ws with default false
ws = False
# open file "yipee.txt" with read only
with open("yipee.txt", "r") as f:
    # pull the raw text from the file into a new variable text
    text = f.read()
    # initiate a for loop for all the letters in text
    for i, letter in enumerate(text):
        # replace the condition with .isspace() and ws == False (was: if letter == " " and ws == False and letter != "\n":)
        # add a condition to check if we are the last letter in the index of text and if we are do not enter the body of the if and not if the letter is a newline (was: if letter.isspace() and ws == False:)
        if letter.isspace() and ws == False and i != len(text) - 1:
            # lets add an if here to check if any letters after our current index to the end of the index have any non isspace or \n characters
            if any(not c.isspace() for c in text[i+1:]):            
                # Increment the variable words by 1 (note: file has `words`, not `word`)
                words += 1
                # Set ws to True
                ws = True
        # if the letter is anything other than a space then set ws to false
        if not letter.isspace():
            if i == 0:
                words += 1
            ws = False

# print words
print(words)