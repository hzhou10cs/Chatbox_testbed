%% SMART Domain Comparison (user-level) across 3 benchmarks
% MATLAB R2025a
%
% For each benchmark file:
%  - Exclude rows with goal_text == 'NONE' (case-insensitive)
%  - For each user and each domain (activity/nutrition/sleep), compute mean(domain_overall)
%  - Output perUserDomain(u,b,d)
% Plot:
%  - 3 domains (categories), each has 3 boxplots (benchmarks) + jittered user points
%
% Required columns (case-insensitive):
%  - user_id
%  - goal_text
%  - domain_overall
%  - domain  (or domain_name / domain_type; see candidates below)
%
% Optional columns:
%  - status_code (keep == 200)
%  - parse_error (drop non-empty)

clear; clc;

% -------------------- USER CONFIG --------------------
xlsxFiles  = { ...
    'eval_results\eval_smart_mode0\results_goals.xlsx', ...   % Benchmark A (replace)
    'eval_results\eval_smart_mode1\results_goals.xlsx', ...   % Benchmark B (replace)
    'eval_results\eval_smart_mode2\results_goals.xlsx'  ...   % Benchmark C (replace)
};
benchNames = {'SSC','MSS','SA'};
nBench = numel(xlsxFiles);

sheetName = 1; % set to 'Sheet1' if needed
% -----------------------------------------------------

% -------------------- DOMAIN CONFIG --------------------
domainKeys  = ["activity","nutrition","sleep"];           % values in the file (lowercase)
domainNames = {'Activity','Nutrition','Sleep'};           % x-axis labels
nDomains = numel(domainKeys);
% ------------------------------------------------------

% -------------------- STYLE ---------------------------
fontName      = 'Helvetica';
axFontSize    = 16;
labelFontSize = 17.6;
legFontSize   = 20;

cBlue   = [0.0353, 0.5176, 0.8902];
cRed    = [0.9098, 0.2549, 0.0941];
cOrange = [0.9294, 0.6941, 0.1255];
colors  = [cRed; cBlue; cOrange];  % A/B/C

boxFaceAlpha = 0.18;
lineW = 3;
% ------------------------------------------------------

% -------------------- READ + AGGREGATE ----------------
% perUserDomain{b} is a map of user->(1x3) domain means, but we convert to matrix later
allUsers = strings(0,1);
perBenchUserDomain = cell(nBench,1);  % each: struct with fields users, mat (nUsers_b x nDomains)

for b = 1:nBench
    [users_b, mat_b] = compute_user_domain_means(xlsxFiles{b}, sheetName, domainKeys);
    perBenchUserDomain{b} = struct('users', users_b, 'mat', mat_b);
    allUsers = union(allUsers, users_b);
end

allUsers = sort(allUsers);
nUsers = numel(allUsers);

% Build unified tensor: perUserDomain(u,b,d)
perUserDomain = NaN(nUsers, nBench, nDomains);
for b = 1:nBench
    users_b = perBenchUserDomain{b}.users;
    mat_b   = perBenchUserDomain{b}.mat;   % (nUsers_b x nDomains)

    [tf, loc] = ismember(users_b, allUsers);
    perUserDomain(loc(tf), b, :) = mat_b(tf, :);
end

% Optional: print quick summary (means + N per domain per benchmark)
fprintf('User-level domain means (excluding goal_text==NONE)\n');
for b = 1:nBench
    fprintf('  %s:\n', benchNames{b});
    for d = 1:nDomains
        y = perUserDomain(:,b,d);
        y = y(~isnan(y));
        fprintf('    %-10s  mean=%.3f  N=%d\n', domainNames{d}, mean(y,'omitnan'), numel(y));
    end
end

% -------------------- PLOT (grouped boxplots) ----------------
fig = figure('Color','w', 'Position',[100 100 900 400]);
ax  = axes(fig); hold(ax,'on');

% Group layout: domain centers at 1..nDomains, with benchmark offsets
offset = [-0.25 0 0.25];  % A/B/C
positions = zeros(nDomains*nBench,1);

vals = [];
grp  = [];

g = 0;
for d = 1:nDomains
    for b = 1:nBench
        g = g + 1;
        positions(g) = d + offset(b);

        y = perUserDomain(:,b,d);
        y = y(~isnan(y));

        vals = [vals; y(:)];
        grp  = [grp;  g*ones(numel(y),1)];
    end
end

boxplot(ax, vals, grp, ...
    'Positions', positions, ...
    'Symbol', '', ...
    'Whisker', 1.5, ...
    'Widths', 0.18);

% Bold boxplot lines
set(findobj(ax,'Type','Line'), 'LineWidth', 2);

% Color each box by benchmark (based on group index)
hBox = findobj(ax, 'Tag', 'Box'); % reverse order
for i = 1:numel(hBox)
    xd = get(hBox(i), 'XData');
    yd = get(hBox(i), 'YData');
    xCenter = mean(xd);

    % nearest group
    [~, gIdx] = min(abs(positions - xCenter));
    bIdx = mod(gIdx-1, nBench) + 1;

    patch('XData', xd, 'YData', yd, ...
        'FaceColor', colors(bIdx,:), 'FaceAlpha', boxFaceAlpha, ...
        'EdgeColor', colors(bIdx,:), 'LineWidth', 2);
end

% Overlay user points (jitter)
% jitter = 0.04;
% for d = 1:nDomains
%     for b = 1:nBench
%         gIdx = (d-1)*nBench + b;
%         x0 = positions(gIdx);
% 
%         y = perUserDomain(:,b,d);
%         y = y(~isnan(y));
% 
%         xj = x0 + (rand(size(y))-0.5)*2*jitter;
%         plot(ax, xj, y, 'o', 'MarkerSize', 5.5, 'LineWidth', 1.2, 'Color', colors(b,:));
%     end
% end

% Axes formatting
xlim(ax, [0.5 nDomains+0.5]);
xticks(ax, 1:nDomains);
xticklabels(ax, domainNames);

ylim(ax, [2 5]);
yticks(ax, 2:1:5);

ylabel(ax, 'SMART Score by Domain', ...
    'FontName', fontName, 'FontSize', labelFontSize, 'FontWeight','bold');

set(ax, 'FontName', fontName, 'FontSize', axFontSize, ...
    'FontWeight','bold', 'LineWidth', 1);

grid(ax,'on');
box(ax,'off');

% Legend (dummy lines)
hLeg = gobjects(1,nBench);
for b = 1:nBench
    hLeg(b) = plot(ax, NaN, NaN, '-', 'LineWidth', lineW, 'Color', colors(b,:));
end
leg = legend(ax, hLeg, benchNames, ...
    'Orientation','horizontal', 'NumColumns', 3, 'Location','south');
set(leg, 'Box','on', 'FontName',fontName, 'FontSize',legFontSize, 'FontWeight','bold');

% Optional export
% exportgraphics(fig, 'smart_domain_boxplot.png', 'Resolution', 300);
% exportgraphics(fig, 'smart_domain_boxplot.pdf', 'ContentType', 'vector');

%% -------------------- LOCAL FUNCTION --------------------
function [userList, userDomainMat] = compute_user_domain_means(xlsxPath, sheetName, domainKeys)
% Compute per-user mean domain_overall for each domain in domainKeys,
% excluding rows where goal_text == 'NONE' (case-insensitive).
%
% Returns:
%  userList: (nUsers x 1) string
%  userDomainMat: (nUsers x nDomains) double, NaN if user lacks that domain

    assert(isfile(xlsxPath), 'Excel file not found: %s', xlsxPath);

    T = readtable(xlsxPath, 'Sheet', sheetName, 'VariableNamingRule','preserve');
    vars = string(T.Properties.VariableNames);
    varsLower = lower(vars);

    % Required columns (case-insensitive)
    iUser = find(varsLower == "user_id", 1);
    iGoal = find(varsLower == "goal_text", 1);
    iOv   = find(varsLower == "domain_overall", 1);

    assert(~isempty(iUser), 'Missing column "user_id" in %s', xlsxPath);
    assert(~isempty(iGoal), 'Missing column "goal_text" in %s', xlsxPath);
    assert(~isempty(iOv),   'Missing column "domain_overall" in %s', xlsxPath);

    % Domain column candidates
    domCandidates = ["domain","domain_name","domain_type","goal_domain"];
    iDom = 0;
    for c = 1:numel(domCandidates)
        hit = find(varsLower == domCandidates(c), 1);
        if ~isempty(hit)
            iDom = hit; break;
        end
    end
    assert(iDom ~= 0, 'Missing a domain column. Tried candidates: %s', strjoin(domCandidates, ", "));

    user = string(T.(vars(iUser)));
    goal = string(T.(vars(iGoal)));
    dom  = string(T.(vars(iDom)));
    ov   = double(T.(vars(iOv)));

    % Base validity
    valid = ~ismissing(user) & ~ismissing(goal) & ~ismissing(dom) & ~ismissing(ov) & isfinite(ov);

    % Optional: status_code == 200
    iStatus = find(varsLower == "status_code", 1);
    if ~isempty(iStatus)
        sc = T.(vars(iStatus));
        valid = valid & ~ismissing(sc) & (sc == 200);
    end

    % Optional: parse_error empty
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

    % Exclude goal_text == NONE
    goalNorm = lower(strtrim(goal));
    valid = valid & ~ismissing(goalNorm) & (goalNorm ~= "none");

    % Normalize fields
    user = lower(strtrim(user(valid)));
    dom  = lower(strtrim(dom(valid)));
    ov   = ov(valid);

    % Keep only requested domains
    keep = false(size(dom));
    for d = 1:numel(domainKeys)
        keep = keep | (dom == domainKeys(d));
    end
    user = user(keep);
    dom  = dom(keep);
    ov   = ov(keep);

    % Clamp safety to [0,5]
    ov = min(5, max(0, ov));

    % Unique users
    userList = unique(user);
    userList = sort(userList);
    nUsers = numel(userList);
    nDomains = numel(domainKeys);

    userDomainMat = NaN(nUsers, nDomains);

    % For each domain, compute per-user mean
    for d = 1:nDomains
        domKey = domainKeys(d);
        selD = (dom == domKey);

        if ~any(selD), continue; end

        [G, uListD] = findgroups(user(selD));
        m = splitapply(@(x) mean(x,'omitnan'), ov(selD), G);

        [tf, loc] = ismember(uListD, userList);
        userDomainMat(loc(tf), d) = m(tf);
    end
end
