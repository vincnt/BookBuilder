from collections import Counter
import addict
import yaml
from config import PRINT_INFO_TO_CONSOLE

import io
import os
import logging
import chess
import chess.pgn


from workerEngineReduce import WorkerEngineReduce
import chess.engine

log_level = logging.INFO
if PRINT_INFO_TO_CONSOLE:
    log_level = logging.DEBUG
logging.basicConfig(level=log_level)

class BookBuilder():
    def __init__(self, config):

        self.working_dir = os.getcwd()
        self.config = config
        logging.info(f'Starting BookBuilder. Your current dir is {self.working_dir}. Files will be saved to this location.')

        self.engine = None
        if (self.config.CAREABOUTENGINE == 1):
            self.engine = chess.engine.SimpleEngine.popen_uci(self.config.ENGINEPATH)  #WHERE THE ENGINE IS ON YOUR COMPUTER
            self.engine.configure({"Hash": self.config.ENGINEHASH})
            self.engine.configure({"Threads": self.config.ENGINETHREADS})
            logging.getLogger('chess.engine').setLevel(logging.INFO)
        self.workerEngineReduce = WorkerEngineReduce(self.config)

    def grower_run(self):
        printers = []
        for chapter, opening in enumerate(self.config.OPENINGBOOK, 1):
            pgn = opening['pgn']
            printer = self.grower_iterator(pgn, opening['Name'])
            filename = f"{self.working_dir}/Chapter_{chapter}_{opening['Name']}.pgn"
            printers.append((printer, filename))

        if (self.engine):    
            self.engine.quit() # quit engine
        if (self.workerEngineReduce.engine):
            self.workerEngineReduce.engine.quit()

        return printers 

    
    def grower_iterator(self, pgn, openingName):
        finalLine = []
        pgnsreturned = []
        
        pgnsreturned = self.grower_calculate_pgn(pgn, pgnsreturned)
            
        secondList = []
        secondList.extend(pgnsreturned) #we create list of pgns and cumulative probabilities returned by starter, calling the api each move 
        # print ("second list",secondList)

        
        # #we iterate through these with leafer, calling the api only for new moves.
        i = 0
        while i < len(secondList):
            for pgn, cumulative, likelyPath in secondList:
                pgnsreturned, finalLine = self.leafer_calculate_pgns(pgn, cumulative, likelyPath, finalLine)
                secondList.extend(pgnsreturned)
                i += 1
                # logging.debug("iterative",secondList)
            
        #print ("final line list: ", finalLine)
        

        #we remove duplicate lines
        uniqueFinalLine = []
        for line in finalLine:
            if line not in uniqueFinalLine:
                uniqueFinalLine.append(line)
        logging.debug(f"unique lines with subsets {uniqueFinalLine}")     
        
        printerFinalLine = [] #we prepare a list ready for printing
        
        # we remove lines that are subsets of other lines because no valid repsonse was found
        for line in uniqueFinalLine:
            uniqueFinalLinestring = str(uniqueFinalLine)
            lineString = str(line[0]) + " "
            lineCount = uniqueFinalLinestring.count(lineString)
            if lineCount == 0:
                printerFinalLine.append(line) #we add line to go to print
            else:
                logging.debug("duplicate line ", line)
            logging.debug(f"final line count { lineCount+1 } for line {lineString}")
        
        
        if self.config.LONGTOSHORT == 1:
            printerFinalLine.reverse() #we make the longest (main lines) first
        

        
        #we print the final list of lines
        logging.debug(f'number of final lines {len(printerFinalLine)}')
        logging.debug(f'final line sorted {printerFinalLine}')
        printer = Printer( )

        lineNumber = 1        
        for pgn, cumulative, likelyPath, winRate, Games in printerFinalLine:
            printer.add(pgn, cumulative, likelyPath, winRate, Games, lineNumber, openingName)
            lineNumber += 1
        return printer
        
    def leafer_calculate_pgns(self, pgn, cumulative, likelyPath, finalLine):
        try:
            game = chess.pgn.read_game(io.StringIO(pgn)) #reads the PGN submitted by the user
        except:
            raise Exception(f'Invalid PGN {pgn}') #error if user submitted PGN is invalid

        board = game.board()
        moves = list(game.mainline_moves()) #we create a list of pgn moves in UCI
        logging.debug(moves)
        
        if len(moves) % 2 == 0: #if even moves in pgn, we are black. if odd, white.
            perspective = chess.BLACK
            perspective_str = 'Black'
        else:
            perspective = chess.WHITE
            perspective_str = 'White'
        

        likelihood = cumulative #likelihood of oppoonent playing moves starts at 100%
        likelihood_path = likelyPath
        validContinuations = [] 
        pgnList = []

        for move in moves: #we iterate through each move in the PGN/UCI generated 
            board.push(move) #play each move in the PGN
            
        #we find all continuations
        workerPlay = self.workerEngineReduce.create_worker(board.fen(), move) #we call the api to get the stats in the position
        continuations = workerPlay.find_move_tree() #list all continuations
        #logging.debug(continuations)       
        
        
        for move in continuations:
            continuationLikelihood = float(move['playrate']) * float(likelihood)
            if (continuationLikelihood >= (float(self.config.DEPTHLIKELIHOOD))) and (move['total_games'] > self.config.CONTINUATIONGAMES): #we eliminate continuations that don't meet depth likelihood or minimum games
                move ['cumulativeLikelihood'] = (continuationLikelihood)
                validContinuations.append(move)
                #print (float(move['playrate']),float(likelihood),float(self.config.DEPTHLIKELIHOOD))
                #logging.debug(continuationLikelihood)
        logging.debug (f'valid continuations: {validContinuations}')
        
        
        
        #now we iterate through each valid continuation, and find our best response
        for move in validContinuations:
            board.push_san(move['san']) #we play each valid continuation
            
            likelihood_path.append((move['san'], move['playrate'])) #we add the continuation to the likelihood path
            
                                    
            #we look for the best move for us to play
            workerPlay = self.workerEngineReduce.create_worker(board.fen(), lastmove = move)
            _, best_move, potency, potency_range, total_games = workerPlay.pick_candidate() #list best candidate move, win rate,
            print_playrate = '{:+.2%}'.format(move['playrate'])
            print_cumulativelikelihood = '{:+.2%}'.format(move['cumulativeLikelihood'])
            print_winrate = "{:+.2%}".format(potency)
            print_potency_range = ["{:.2%}".format(x) for x in potency_range]
            logging.debug(f"against {move['san']} played {print_playrate} cumulative playrate {print_cumulativelikelihood} our best move {best_move} win rate is {print_winrate} with a range of {print_potency_range} over {total_games} games")
            
            #we check our response playrate and minimum played games meet threshold. if so we pass the pgn. if not we add pgn to final list
            
            if (move['playrate'] > self.config.MINPLAYRATE) and (total_games >self.config.MINGAMES) and (potency != 0):
                
                #we add the pgn of the continuation and our best move to a list
                if  perspective_str == 'Black':
                    newpgn = pgn + " " + str(board.fullmove_number) + ". " + str(move['san']) #we add opponent's continuations first
                    newpgn = newpgn + " " + str(best_move) #then our best response
                    pgnPlus = [newpgn, move ['cumulativeLikelihood'], likelihood_path[:]]
                    #need to return a pgn as well as moves + chance + cumulative likelihood
                        

                if  perspective_str == 'White':
                    newpgn = pgn + " " + move['san'] #we add opponent's continuations first
                    newpgn = newpgn + " " + str(board.fullmove_number) + ". " + str(best_move) #then our best response
                    pgnPlus = [newpgn, move ['cumulativeLikelihood'], likelihood_path[:]]          
                logging.debug(f"full new pgn after our move is {newpgn}")        
                
                #we make a list of pgns that we want to feed back into the algorithm, along with cumulative winrates
                pgnList.append(pgnPlus)
                #logging.debug(pgnList)
                del likelihood_path [-1] #we remove the continuation from the likelihood path                         
                board.pop() #we go back a move to undo the continuation
            else:
                if (self.config.CAREABOUTENGINE == 1) and (self.config.ENGINEFINISH ==1): #if we want engine to finish lines where no good move data exists
                    
                    #we ask the engine the best move
                    PlayResult = self.engine.play(board, chess.engine.Limit(depth = self.config.ENGINEDEPTH)) #we get the engine to finish the line
                    board.push(PlayResult.move)
                    logging.debug(f"engine finished {PlayResult.move}")
                    board.pop() #we go back a move to undo the engine
                    
                    engineMove = board.san(PlayResult.move)
                    
                    #we add the pgn of the continuation and our best move to a list
                    if  perspective_str == 'Black':
                        newpgn = pgn + " " + str(board.fullmove_number) + ". " + str(move['san']) #we add opponent's continuations first
                        newpgn = newpgn + " " + str(engineMove) #then our best response
                        pgnPlus = [newpgn, move ['cumulativeLikelihood'], likelihood_path[:]]
                        #need to return a pgn as well as moves + chance + cumulative likelihood
                            

                    if  perspective_str == 'White':
                        newpgn = pgn + " " + move['san'] #we add opponent's continuations first
                        newpgn = newpgn + " " + str(board.fullmove_number) + ". " + str(engineMove) #then our best response
                        pgnPlus = [newpgn, move ['cumulativeLikelihood'], likelihood_path[:]]          
                    logging.debug(f"full new pgn after our move is {newpgn}")        
                    
                    #we make a list of pgns that we want to feed back into the algorithm, along with cumulative winrates
                    pgnList.append(pgnPlus)
                    #logging.debug(pgnList)
                    del likelihood_path [-1] #we remove the continuation from the likelihood path                         
                    board.pop() #we go back a move to undo the continuation
                        
                                    
                
                else:
                    logging.debug(f"we find no good reply to {pgn} {move['san']}")
                    board.pop() #we go back a move to undo the continuation
                    del likelihood_path [-1] #we remove the continuation from the likelihood path    
                    #we find potency and other stats
                    workerPlay = self.workerEngineReduce.create_worker(board.fen(), move) #we call the api to get the stats in the final position
                    lineWinRate, totalLineGames, throwawayDraws = workerPlay.find_potency() #we get the win rate and games played in the final position            
                    logging.debug (f'saving no reply line {pgn} {likelihood} {likelihood_path} {lineWinRate} {totalLineGames}')
                    line = (pgn, likelihood, likelihood_path,lineWinRate, totalLineGames)
                    finalLine.append(line) #we add line to final line list                                 
                
                
        pgnsreturned = pgnList #we define the variable as the completely made list of continuations and responses and send it to be extended to second list

        #if there are no valid continuations we save the line to a file
        if not validContinuations:
            
            #we find potency and other stats
            workerPlay = self.workerEngineReduce.create_worker(board.fen(), move) #we call the api to get the stats in the final position
            lineWinRate, totalLineGames, throwawayDraws = workerPlay.find_potency() #we get the win rate and games played in the final position            
            

            if (totalLineGames == 0) and (lineWinRate == 1): #if the line ends in mate  there are no games played from the position so we need to populate games number from last move
                board.pop()
                workerPlay = self.workerEngineReduce.create_worker(board.fen(), move) #we call the api to get the stats in the final position
                throwawayWinRate, totalLineGames, throwawayDraws = workerPlay.find_potency() #we get the win rate and games played in the pre Mate position
            
            if (totalLineGames < self.config.MINGAMES) : #if our response is an engine 'novelty' there is no reliable lineWinRate or total games
                board.pop() #we go back to opponent's move
                workerPlay = self.workerEngineReduce.create_worker(board.fen(), move)
                lineWinRate, totalLineGames, draws = workerPlay.find_potency()


                if self.config.DRAWSAREHALF == 1: #if draws are half we inverse the winrate on the last move, and add half the draws
                    lineWinRate = 1 - lineWinRate + (0.5 * draws)
                    logging.debug(f"total games on previous move: {totalLineGames}, draws are wins and our move is engine 'almost novelty' so win rate based on previous move is {lineWinRate}")  
                else:
                    
                    lineWinRate = 1 - lineWinRate - draws #if draws aren't half we inverse the winrate and remove minus the draws
                    logging.debug(f"total games on previous move: {totalLineGames}, draws aren't wins and our move is engine 'almost novelty' so win rate based on prev move is {lineWinRate}")                  
                

            line = (pgn, likelihood, likelihood_path, lineWinRate, totalLineGames)
            finalLine.append(line) #we add line to final line list 
            
        return pgnsreturned, finalLine
            

    def grower_calculate_pgn(self, pgn, pgnsreturned):
        
        try:
            game = chess.pgn.read_game(io.StringIO(pgn)) #reads the PGN submitted by the user
        except:
            raise Exception(f'Invalid PGN {pgn}') #error if user submitted PGN is invalid

        board = game.board()
        moves = list(game.mainline_moves()) #we create a list of pgn moves in UCI
        logging.debug(moves)
        

        if len(moves) % 2 == 0: #if even moves in pgn, we are black. if odd, white.
            perspective = chess.BLACK
            perspective_str = 'Black'
        else:
            perspective = chess.WHITE
            perspective_str = 'White'
        

        likelihood = 1 #likelihood of oppoonent playing moves starts at 100%
        likelihood_path = []
        validContinuations = [] 
        pgnList = []

        for move in moves: #we iterate through each move in the PGN/UCI generated
            
            if board.turn != perspective: #if it's not our move we check the likelihood the move in the PGN was played
                workerPlay = self.workerEngineReduce.create_worker(board.fen()) #we are calling the API each time
                move_stats, chance = workerPlay.find_opponent_move(move) #we look for the PGN move in the API response, and return the odds of it being played
                likelihood *= chance #we are creating a cumulative likelihood from each played move in the PGN
                likelihood_path.append((move_stats['san'], chance)) #we are creating a list of PGN moves with the chance of each of them being played 0-1
                logging.debug(f"likelihoods to get here: {likelihood_path}")
                logging.debug(f"cumulative likelihood {'{:+.2%}'.format(likelihood)}", )
            board.push(move) #play each move in the PGN
        
        #now we have the likelihood path and cumulative likelihood of each opponent move in the PGN, so pgn can go to leafer
        
        pgnPlus = pgn, likelihood, likelihood_path
        

        pgnsreturned.append(pgnPlus)
        logging.debug(f"sent from rooter: {pgnsreturned}")
        return pgnsreturned

        
class Printer():
    def __init__(self):
        self.content = ''

    def add(self, pgn, cumulative, likelyPath, winRate, Games, lineNumber, openingName):
        pgnEvent = '[Event "' + openingName + " Line " + str(lineNumber) + '"]' #we name the event whatever you put in config
        # annotation = "{likelihoods to get here:" + str(self.likelihood_path) + ". Cumulative likelihood" + str("{:+.2%}".format(self.likelihood)) + " }" #we create annotation with opponent move likelihoods and our win rate
        
        self.content += f'\n\n\n{pgnEvent}\n'  #write name of pgn
        self.content += '\n'
        self.content += f'{pgn}' #write pgn
        self.content += '\n'
        self.content += "{Move playrates:" #start annotations
        
        for move, chance in likelyPath:
            moveAnnotation = str("{:+.2%}".format(chance)) + '\t' + move
            self.content += '\n'
            self.content += moveAnnotation
        
        
        #we write them in as annotations
        lineAnnotations = "Line cumulative playrate: " + str("{:+.2%}".format(cumulative)) + '\n' + "Line winrate: " + str("{:+.2%}".format(winRate)) + ' over ' + str(Games) + ' games'
        self.content += '\n'
        self.content += lineAnnotations
        
        self.content += "}" #end annotations                

    def save_to_file(self, filepath):
        with open(filepath, 'w') as file:
            file.write(self.content)
        logging.info(f"Wrote data to {filepath}")


if __name__=='__main__':
    # You can store your '/config.yaml' location here if you are running this with python and don't want to reinput it everytime
    # eg change 'None' to something like 'C:\Dropbox\Chess\BookBuilder-main\config.yaml'
    yaml_location = '/Users/vincenttan/Code/work/BookBuilder/config.yaml'

    if yaml_location is None:
        yaml_location = input('What is the full path to your config.yaml file? (ie. /Users/youruser/BookBuilder/config.yaml): ')
    while not os.path.exists(yaml_location):
            yaml_location = input('The location you have input does not exist, please try again: ')

    print("Loading config file...")
    with open(yaml_location, "r") as f:
        config = addict.Dict(yaml.safe_load(f))

    print(f"File loaded!")

    if config.CAREABOUTENGINE==1:
        if not os.path.exists(config.ENGINEPATH):
            logging.error(f"The path ({config.ENGINEPATH}) you have provided for ENGINEPATH in the config file does not exist. Please fix that and run the program again.")
    
    # Run the program
    bookbuilder = BookBuilder(config)
    printers = bookbuilder.grower_run()
  
    # Save contents to file
    for printer, filename in printers:
        printer.save_to_file(filename)
    

