%% (1) Simulate data for proactivity evaluation and save to .mat
% MATLAB R2025a

clear; clc;

rng(2026);  % reproducible

nUsers = 10;
nBench = 3;
nChatsPerUser = 5;

benchNames = {'Benchmark A','Benchmark B','Benchmark C'};

% Categories: scores are ordinal 0/1/2
scoreLevels = [0 1 2];

% Total rounds per user per benchmark: random 80-120
minTotal = 80;
maxTotal = 120;

% Simulate baseline differences across benchmarks:
% Higher mean proactivity in later benchmarks (example)
benchShift = [0.00, 0.10, 0.20];  % affects probability of score=2 vs 0

% User random effect (some users are more proactive)
userShift = 0.15 * randn(nUsers,1);

% A struct array of all rounds
idx = 0;
records = struct('user',{},'bench',{},'chat',{},'round_in_chat',{}, ...
                 'global_round',{},'score',{});

for u = 1:nUsers
    for b = 1:nBench
        totalRounds = randi([minTotal, maxTotal], 1, 1);

        % Split into 5 chats with unequal lengths, sum to totalRounds
        % Use random positive integers then normalize
        raw = rand(1, nChatsPerUser);
        lens = max(5, round(raw/sum(raw) * totalRounds));  % at least 5 rounds per chat
        % Fix sum exactly to totalRounds
        diff = totalRounds - sum(lens);
        while diff ~= 0
            k = randi(nChatsPerUser);
            if diff > 0
                lens(k) = lens(k) + 1;
                diff = diff - 1;
            else
                if lens(k) > 5
                    lens(k) = lens(k) - 1;
                    diff = diff + 1;
                end
            end
        end

        % Generate scores round-by-round
        g = 0;
        for c = 1:nChatsPerUser
            for r = 1:lens(c)
                g = g + 1;

                % Progress effect: slightly more proactive later in the conversation
                progress = (g - 1) / max(1, totalRounds - 1);  % 0..1
                progShift = 0.10 * (progress - 0.5);           % small

                % Convert shifts to probabilities for 0/1/2 (softmax-like)
                sUser  = userShift(u);
                sBench = benchShift(b);
                sProg  = progShift;

                % logits for (0,1,2): center at 1, shifts push mass to 2
                logit0 = 0.30 - 1.2*(sUser + sBench + sProg);
                logit1 = 0.60;
                logit2 = 0.30 + 1.2*(sUser + sBench + sProg);

                logits = [logit0, logit1, logit2];
                p = exp(logits - max(logits));
                p = p / sum(p);

                sc = randsample(scoreLevels, 1, true, p);

                idx = idx + 1;
                records(idx).user = u;
                records(idx).bench = b;
                records(idx).chat = c;
                records(idx).round_in_chat = r;
                records(idx).global_round = g;
                records(idx).score = sc;
            end
        end
    end
end

% Convert to table for easier analysis
T = struct2table(records);

% Save
save('sim_proactivity.mat', 'T', 'benchNames', 'nUsers', 'nBench', 'nChatsPerUser');

disp('Saved simulated dataset to sim_proactivity.mat');
