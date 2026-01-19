%% (0) Generate synthetic SMART dataset and save to sim_smart.mat
% Structure:
% scores(u,b,d,s,k) in [0..5], integers
% u: user (1..10)
% b: benchmark (A/B/C) (1..3)
% d: domain (1..3)
% s: session (1..5)
% k: dimension (S/M/A/R/T) (1..5)

clear; clc;

rng(2026);

nUsers    = 10;
nBench    = 3;
nDomains  = 3;
nSessions = 5;
nDims     = 5;

benchNames  = {'Benchmark A','Benchmark B','Benchmark C'};
domainNames = {'Domain 1','Domain 2','Domain 3'};
dimNames    = {'Specific','Measurable','Achievable','Relevant','Time-bound'}; % S/M/A/R/T

% Colors (given)
cBlue   = [0.0353, 0.5176, 0.8902];
cRed    = [0.9098, 0.2549, 0.0941];
cOrange = [0.9294, 0.6941, 0.1255];
colors  = [cRed; cBlue; cOrange];  % A/B/C

% ---- Synthetic effects (you can tune these easily) ----
% Benchmark shift: A < B < C (example)
benchShift = [0.0, 0.4, 0.8];           % additive shift on latent mean

% Domain difficulty (example)
domainShift = [0.2, -0.1, 0.0];         % domain-specific shift

% Dimension profile (example: Time-bound tends to be lower)
dimShift = [0.0, 0.0, 0.1, 0.1, -0.4];  % S M A R T

% User random effect
userShift = 0.6 * randn(nUsers,1);

% Session drift (optional): slight improvement over sessions
sessionShift = linspace(-0.1, 0.1, nSessions);

% Noise scale
sigma = 0.9;

% ---- Generate scores ----
scores = zeros(nUsers, nBench, nDomains, nSessions, nDims);

for u = 1:nUsers
    for b = 1:nBench
        for d = 1:nDomains
            for s = 1:nSessions
                for k = 1:nDims
                    latent = 2.5 ...
                        + benchShift(b) ...
                        + domainShift(d) ...
                        + dimShift(k) ...
                        + userShift(u) ...
                        + sessionShift(s) ...
                        + sigma*randn();

                    % Clamp to [0,5] and round to integer
                    sc = round(min(5, max(0, latent)));
                    scores(u,b,d,s,k) = sc;
                end
            end
        end
    end
end

save('sim_smart.mat', ...
    'scores','benchNames','domainNames','dimNames', ...
    'nUsers','nBench','nDomains','nSessions','nDims', ...
    'colors');

disp('Saved synthetic SMART dataset to sim_smart.mat');
