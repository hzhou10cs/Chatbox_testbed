%% Figure 1 (Revised Main Plot): Boxplot of per-user mean proactivity score across benchmarks
% Goal:
%   Show distribution (across users) of mean proactivity score for each benchmark.
% X-axis: 3 benchmarks
% Y-axis: proactivity score (0/1/2, averaged -> continuous in [0,2])
%
% Data assumption:
%   sim_proactivity.mat contains:
%     - T: table with columns user, bench, score
%     - benchNames, nUsers, nBench
clear; clc;

% -------------------- USER CONFIG --------------------
xlsxFiles  = { ...
    'eval_results\eval_proactivity_mode0\results_sessions.xlsx', ...   % Benchmark A (replace)
    'eval_results\eval_proactivity_mode1\results_sessions.xlsx', ...   % Benchmark B (replace)
    'eval_results\eval_proactivity_mode2\results_sessions.xlsx'  ...   % Benchmark C (replace)
};

benchNames = {'SSC','MSS','SA'};
nBench = numel(xlsxFiles);
% -----------------------------------------------------

% -------------------- STYLE ---------------------------
fontName      = 'Helvetica';
axFontSize    = 16;
labelFontSize = 17.6;

cBlue   = [0.0353, 0.5176, 0.8902];
cRed    = [0.9098, 0.2549, 0.0941];
cOrange = [0.9294, 0.6941, 0.1255];
colors  = [cRed; cBlue; cOrange];   % A/B/C
% -----------------------------------------------------

% -------------------- LOAD & AGGREGATE ----------------
benchScores = cell(nBench,1);
benchUsers  = cell(nBench,1);

for b = 1:nBench
    [benchScores{b}, benchUsers{b}] = load_user_proactivity_scores(xlsxFiles{b});
end

% Build boxplot vectors (allow unequal #users across benchmarks)
vals = [];
grp  = [];
for b = 1:nBench
    v = benchScores{b};
    v = v(~isnan(v));                 % drop invalid users
    vals = [vals; v(:)];
    grp  = [grp;  b*ones(numel(v),1)];
end

% -------------------- PLOT ----------------------------
fig = figure('Color','w', 'Position',[100 100 600 500]);
ax  = axes(fig); hold(ax, 'on');

boxplot(ax, vals, grp, ...
    'Labels', benchNames, ...
    'Symbol', '', ...
    'Whisker', 1.5, ...
    'Widths', 0.55);

% Bold boxplot lines
set(findobj(ax,'Type','Line'), 'LineWidth', 2);

% Color boxes robustly by reading their x-center
hBox = findobj(ax, 'Tag', 'Box');  % returned in reverse order
for i = 1:numel(hBox)
    xd = get(hBox(i), 'XData');
    yd = get(hBox(i), 'YData');
    xCenter = mean(xd);

    % Map to nearest benchmark index (1..nBench)
    bIdx = round(xCenter);
    bIdx = max(1, min(nBench, bIdx));

    patch('XData', xd, 'YData', yd, ...
        'FaceColor', colors(bIdx,:), 'FaceAlpha', 0.18, ...
        'EdgeColor', colors(bIdx,:), 'LineWidth', 2);
end

% Overlay per-user points with jitter (per benchmark)
jitterAmount = 0.10;
for b = 1:nBench
    y = benchScores{b};
    y = y(~isnan(y));
    x0 = b;
    xj = x0 + (rand(size(y))-0.5) * 2 * jitterAmount;
    plot(ax, xj, y, 'o', 'MarkerSize', 6, 'LineWidth', 1.5, 'Color', colors(b,:));
end


% ---------------- Axes formatting ----------------
ylim(ax, [0 2]);
yticks(ax, 0:0.5:2);

ylabel(ax, 'Proactivity Score', ...
    'FontName', fontName, 'FontSize', labelFontSize, 'FontWeight', 'bold');

set(ax, 'FontName', fontName, 'FontSize', axFontSize, ...
    'FontWeight', 'bold', 'LineWidth', 1);
grid(ax, 'on');
box(ax, 'off');

% Optional: tighten x-limits slightly for aesthetics
xlim(ax, [0.5, nBench+0.5]);

% Optional export
% exportgraphics(fig, 'main_boxplot_user_mean.png', 'Resolution', 300);
% exportgraphics(fig, 'main_boxplot_user_mean.pdf', 'ContentType', 'vector');

%% -------------------- LOCAL FUNCTION --------------------
function [userScore, userList] = load_user_proactivity_scores(xlsxPath)
%LOAD_USER_PROACTIVITY_SCORES Compute per-user proactivity score from one results_sessions.xlsx

    assert(isfile(xlsxPath), 'Excel file not found: %s', xlsxPath);

    T = readtable(xlsxPath, 'VariableNamingRule','preserve');
    vars = string(T.Properties.VariableNames);
    varsLower = lower(vars);

    % Required columns (case-insensitive match)
    iUser  = find(varsLower == "user_id", 1);
    iTurn  = find(varsLower == "num_assistant_turns", 1);
    iS2    = find(varsLower == "num_score2", 1);
    iS12   = find(varsLower == "num_score1_or_2", 1);

    assert(~isempty(iUser), 'Missing column "user_id" in %s', xlsxPath);
    assert(~isempty(iTurn), 'Missing column "num_assistant_turns" in %s', xlsxPath);
    assert(~isempty(iS2),   'Missing column "num_score2" in %s', xlsxPath);
    assert(~isempty(iS12),  'Missing column "num_score1_or_2" in %s', xlsxPath);

    user = string(T.(vars(iUser)));
    nTurn = T.(vars(iTurn));
    nS2   = T.(vars(iS2));
    nS12  = T.(vars(iS12));

    % Base validity
    valid = ~ismissing(user) & ~ismissing(nTurn) & isfinite(nTurn);

    % Optional filters: status_code == 200
    iStatus = find(varsLower == "status_code", 1);
    if ~isempty(iStatus)
        sc = T.(vars(iStatus));
        valid = valid & ~ismissing(sc) & (sc == 200);
    end

    % Optional filters: parse_error empty
    iParse = find(varsLower == "parse_error", 1);
    if ~isempty(iParse)
        pe = T.(vars(iParse));
        okParse = true(height(T),1);

        if iscell(pe)
            okParse = cellfun(@(x) isempty(x) || (ischar(x) && isempty(strtrim(x))) || (isstring(x) && strlength(x)==0), pe);
        elseif isstring(pe)
            okParse = ismissing(pe) | (strlength(pe)==0);
        end

        valid = valid & okParse;
    end

    user = lower(strtrim(user(valid)));
    nTurn = nTurn(valid);
    nS2   = nS2(valid);
    nS12  = nS12(valid);

    % Treat missing numeric as 0 for sums
    nTurn = fillmissing(nTurn, 'constant', 0);
    nS2   = fillmissing(nS2,   'constant', 0);
    nS12  = fillmissing(nS12,  'constant', 0);

    % Group by user
    [G, userList] = findgroups(user);

    sumTurn = splitapply(@(x) sum(x,'omitnan'), nTurn, G);
    sumS2   = splitapply(@(x) sum(x,'omitnan'), nS2,   G);
    sumS12  = splitapply(@(x) sum(x,'omitnan'), nS12,  G);

    sumS1 = sumS12 - sumS2;
    sumS1 = max(sumS1, 0);  % guard against negative due to inconsistent inputs

    userScore = NaN(size(sumTurn));
    ok = (sumTurn > 0);
    userScore(ok) = (2*sumS2(ok) + sumS1(ok)) ./ sumTurn(ok);

    % Ensure outputs are column vectors
    userScore = userScore(:);
    userList  = string(userList(:));
end