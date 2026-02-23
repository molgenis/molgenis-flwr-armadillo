## Running flower simulations


## Authentication with flower & Armadillo
The plan is to replicate the structure of auth with DataSHIELD, ie the user requests a token prior to connecting, and 
passes this token to Armadillo when running the application. The flow for this is: 

1. Define the ky in pyproject.toml
[tool.flwr.app.config]
   num-server-rounds = 1
   fraction-train = 0.5
   local-epochs = 1
   lr = 0.01
   auth-token = ""

User → run_config (via CLI) → ServerApp → ConfigRecord → ClientApp

1. User starts the run with their token:              
```
flwr run . --run-config 'auth-token="user_token_here"'
```

2. ServerApp reads it and passes to clients:
```
# server_app.py
@app.main()                                                                                                                                                                                                                           
def main(grid: Grid, context: Context):                                                                                                                                                                                               
token = context.run_config["auth-token"]
print(f"Token: {token}")

strategy.start(                                                                                                                                                                                                                   
    grid=grid,                                                                                                                                                                                                                    
    initial_arrays=arrays,                                                                                                                                                                                                        
    train_config=ConfigRecord({"auth-token": token, "lr": lr}),                                                                                                                                                                   
    num_rounds=num_rounds,                                                                                                                                                                                                        
)     
```
                            

3. ClientApp receives it via the message:

```
@app.train()                                                                                                                                                                                                                          
def train(msg: Message, context: Context):                                                                                                                                                                                            
token = msg.content["config"]["auth-token"]                                                                                                                                                                                       
```

Nice, this works. Next we need each node to self-identify.

