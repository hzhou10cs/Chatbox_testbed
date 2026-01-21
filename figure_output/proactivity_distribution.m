%% Proactivity distribution (0/1/2) by benchmark from Excel (stacked % bars)
% MATLAB R2025a
%
% For each file (one benchmark), compute TOTAL counts across all rows:
%   total_turns = sum(num_assistant_turns)
%   count2      = sum(num_score2)
%   count1      = sum(num_score1_or_2) - count2
%   count0      = total_turns - sum(num_score1_or_2)
% Then convert to percentages and plot stacked bars.

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
fontName = 'Helvetica';
axFontSize = 16;
labelFontSize = 17.6;

% Score colors (0/1/2) — use your specified palette order
cBlue   = [0.0353, 0.5176, 0.8902];
cRed    = [0.9098, 0.2549, 0.0941];
cOrange = [0.9294, 0.6941, 0.1255];
cmap = [cRed; cBlue; cOrange];   % Score=0/1/2
% -----------------------------------------------------

% -------------------- LOAD & COMPUTE ------------------
P = zeros(nBench, 3); % columns: score=0,1,2 (proportions)

for b = 1:nBench
    [c0, c1, c2, totalTurns] = load_total_score_counts(xlsxFiles{b});

    if totalTurns <= 0
        P(b,:) = [NaN NaN NaN];
    else
        P(b,1) = c0 / totalTurns;
        P(b,2) = c1 / totalTurns;
        P(b,3) = c2 / totalTurns;
    end
end

% -------------------- PLOT ----------------------------
fig = figure('Color','w', 'Position',[100 100 600 500]);
ax = axes(fig); hold(ax,'on');

gap = 1.4;
x = (1:nBench) * gap;

bh = bar(ax, x, 100*P, 'stacked', 'LineWidth', 1);
for k = 1:3
    bh(k).FaceColor = cmap(k,:);
    bh(k).BarWidth  = 0.6;
end

xticks(ax, x);
xticklabels(ax, benchNames);
xlim(ax, [x(1)-0.8, x(end)+0.8]);

ylim(ax, [0 100]);

ylabel(ax, 'Percentage of Rounds (%)', ...
    'FontName',fontName, 'FontSize',labelFontSize, 'FontWeight','bold');

set(ax, 'FontName',fontName, 'FontSize',axFontSize, ...
    'FontWeight','bold', 'LineWidth',1);

grid(ax, 'on');
box(ax, 'off');

leg = legend(ax, {'Score=0','Score=1','Score=2'}, ...
    'Location','northoutside', 'Orientation','horizontal');
set(leg, 'Box','on', 'FontName',fontName, ...
    'FontSize',axFontSize, 'FontWeight','bold');

% Optional export
% exportgraphics(fig, 'proactivity_distribution.png', 'Resolution', 300);
% exportgraphics(fig, 'proactivity_distribution.pdf', 'ContentType', 'vector');

%% -------------------- LOCAL FUNCTION --------------------
function [count0, count1, count2, totalTurns] = load_total_score_counts(xlsxPath)
%LOAD_TOTAL_SCORE_COUNTS Read one results_sessions.xlsx and compute total 0/1/2 counts.

    assert(isfile(xlsxPath), 'Excel file not found: %s', xlsxPath);

    T = readtable(xlsxPath, 'VariableNamingRule','preserve');
    vars = string(T.Properties.VariableNames);
    varsLower = lower(vars);

    % Required columns (case-insensitive)
    iTurn = find(varsLower == "num_assistant_turns", 1);
    iS2   = find(varsLower == "num_score2", 1);
    iS12  = find(varsLower == "num_score1_or_2", 1);

    assert(~isempty(iTurn), 'Missing column "num_assistant_turns" in %s', xlsxPath);
    assert(~isempty(iS2),   'Missing column "num_score2" in %s', xlsxPath);
    assert(~isempty(iS12),  'Missing column "num_score1_or_2" in %s', xlsxPath);

    nTurn = T.(vars(iTurn));
    nS2   = T.(vars(iS2));
    nS12  = T.(vars(iS12));

    % Base validity
    valid = ~ismissing(nTurn) & isfinite(nTurn);

    % Optional: keep only successful rows if status_code exists
    iStatus = find(varsLower == "status_code", 1);
    if ~isempty(iStatus)
        sc = T.(vars(iStatus));
        valid = valid & ~ismissing(sc) & (sc == 200);
    end

    % Optional: drop parse_error rows if parse_error exists
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

    nTurn = fillmissing(nTurn(valid), 'constant', 0);
    nS2   = fillmissing(nS2(valid),   'constant', 0);
    nS12  = fillmissing(nS12(valid),  'constant', 0);

    totalTurns = sum(nTurn, 'omitnan');
    sumS2  = sum(nS2,  'omitnan');
    sumS12 = sum(nS12, 'omitnan');

    % Derive counts
    count2 = sumS2;
    count1 = sumS12 - sumS2;
    count0 = totalTurns - sumS12;

    % Guards against inconsistent inputs
    count1 = max(count1, 0);
    count0 = max(count0, 0);
end
